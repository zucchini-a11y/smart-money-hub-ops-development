import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { randomUUID } from "node:crypto";
import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { createServer } from "node:net";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { test } from "node:test";
import { hashPassword } from "../src/lib/portal-crypto.ts";

const requireFromDb = createRequire(new URL("../../../lib/db/package.json", import.meta.url));
const { Pool } = requireFromDb("pg");
const pool = process.env.DATABASE_URL ? new Pool({ connectionString: process.env.DATABASE_URL }) : null;
const enabled = process.env.SMH_TASK_E2E_DEV === "1";

async function stopChrome(chrome, profile) {
  if (chrome.exitCode === null && chrome.signalCode === null) {
    const exited = new Promise((resolve) => chrome.once("exit", () => resolve("exit")));
    chrome.kill("SIGTERM");
    let timer;
    const timeout = new Promise((resolve) => {
      timer = setTimeout(() => resolve("timeout"), 2500);
      timer.unref();
    });
    const result = await Promise.race([exited, timeout]);
    clearTimeout(timer);
    if (result === "timeout") {
      const killed = new Promise((resolve) => chrome.once("exit", resolve));
      chrome.kill("SIGKILL");
      await killed;
    }
  }
  await rm(profile, { recursive: true, force: true, maxRetries: 10, retryDelay: 150 });
}

async function startBrowser() {
  const portServer = createServer();
  await new Promise((resolve) => portServer.listen(0, "127.0.0.1", resolve));
  const port = portServer.address().port;
  await new Promise((resolve) => portServer.close(resolve));
  const profile = await mkdtemp(join(tmpdir(), "smh-portal-ui-"));
  const chrome = spawn(process.env.CHROMIUM_PATH ?? "/repl/tools/bin/chromium", [
    "--headless=new", "--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu",
    "--remote-allow-origins=*", `--remote-debugging-port=${port}`,
    `--user-data-dir=${profile}`, "--window-size=1440,1100", "about:blank",
  ], { stdio: "ignore" });
  let target;
  try {
    const until = Date.now() + 15000;
    while (Date.now() < until) {
      try {
        const response = await fetch(`http://127.0.0.1:${port}/json/new?about:blank`, { method: "PUT" });
        if (response.ok) { target = await response.json(); break; }
      } catch {}
      await new Promise((resolve) => setTimeout(resolve, 150));
    }
    assert.ok(target?.webSocketDebuggerUrl, "headless Chromium DevTools endpoint did not start");
    const socket = new WebSocket(target.webSocketDebuggerUrl);
    await new Promise((resolve, reject) => {
      socket.onopen = resolve;
      socket.onerror = reject;
    });
    let sequence = 0;
    const pending = new Map();
    socket.onmessage = (event) => {
      const message = JSON.parse(event.data);
      if (message.id && pending.has(message.id)) {
        const { resolve, reject, method } = pending.get(message.id);
        pending.delete(message.id);
        message.error ? reject(new Error(`Chromium ${method} failed: ${message.error.message}`)) : resolve(message.result ?? {});
      }
    };
    const send = (method, params = {}) => new Promise((resolve, reject) => {
      const id = ++sequence;
      pending.set(id, { resolve, reject, method });
      socket.send(JSON.stringify({ id, method, params }));
    });
    await send("Page.enable");
    await send("Runtime.enable");
    return {
      async evaluate(expression) {
        const result = await send("Runtime.evaluate", {
          expression, awaitPromise: true, returnByValue: true,
        });
        if (result.exceptionDetails) throw new Error("Browser evaluation failed");
        return result.result?.value;
      },
      async navigate(url) { await send("Page.navigate", { url }); },
      async clearCookies() { await send("Network.enable"); await send("Network.clearBrowserCookies"); },
      async setViewport(width, height) {
        await send("Emulation.setDeviceMetricsOverride", {
          width, height, deviceScaleFactor: 1, mobile: width <= 600,
        });
      },
      async screenshot(path) {
        const result = await send("Page.captureScreenshot", { format: "png", captureBeyondViewport: false });
        await writeFile(path, Buffer.from(result.data, "base64"));
      },
      async close() {
        socket.close();
        await stopChrome(chrome, profile);
      },
    };
  } catch (error) {
    await stopChrome(chrome, profile);
    throw error;
  }
}

async function waitForBrowserValue(browser, expression, timeoutMs = 12000) {
  const until = Date.now() + timeoutMs;
  while (Date.now() < until) {
    const value = await browser.evaluate(expression);
    if (value) return value;
    await new Promise((resolve) => setTimeout(resolve, 150));
  }
  throw new Error("Expected authenticated portal UI state did not appear.");
}

test("authenticated staff task, reports, performance, and reminders E2E (Development only)", { skip: !enabled }, async () => {
  assert.ok(pool, "Development DATABASE_URL must be available; its value is never printed");
  assert.equal(process.env.NODE_ENV, "development", "E2E must run in Development");
  assert.equal(process.env.PORTAL_SUPPORT_SCHEMA, "smh_test", "E2E must use isolated portal support schema");
  const dbCheck = await pool.query("SELECT current_database() AS name");
  assert.equal(dbCheck.rows[0]?.name, "heliumdb", "E2E database must match the verified Development database");

  const run = randomUUID();
  const suffix = run.replaceAll("-", "");
  const ownerId = `task-e2e-owner-${suffix}`;
  const managerId = `task-e2e-manager-${suffix}`;
  const agentId = `task-e2e-agent-${suffix}`;
  const outsideAgentId = `task-e2e-outside-${suffix}`;
  const ownerEmail = `task-e2e-owner-${suffix}@example.invalid`;
  const managerEmail = `task-e2e-manager-${suffix}@example.invalid`;
  const ownerPassword = `Test-only-${randomUUID()}-${randomUUID()}`;
  const managerPassword = `Test-only-${randomUUID()}-${randomUUID()}`;
  const agentPassword = `Test-only-${randomUUID()}-${randomUUID()}`;
  const outsidePassword = `Test-only-${randomUUID()}-${randomUUID()}`;
  const userIds = [ownerId, managerId, agentId, outsideAgentId];
  const requestIds = [`task-e2e-${suffix}-individual`, `task-e2e-${suffix}-team`, `task-e2e-${suffix}-reassign`];
  const teamIds = [];
  const taskIds = [];
  const reportIds = [];
  const supportCaseIds = [`e2e-support-case-${suffix}`];
  const supportReplyIds = [`e2e-support-reply-${suffix}`];
  const apiBase = process.env.SMH_TASK_E2E_API ?? "http://127.0.0.1:8080/api";
  const origin = new URL(apiBase).origin;
  let seeded = false;

  async function call(path, { method = "GET", cookie, body } = {}) {
    const response = await fetch(`${apiBase}${path}`, {
      method,
      headers: {
        ...(body === undefined ? {} : { "content-type": "application/json" }),
        ...(method === "GET" ? {} : { origin }),
        ...(cookie ? { cookie } : {}),
      },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    const text = await response.text();
    let payload = null;
    try { payload = text ? JSON.parse(text) : null; } catch {}
    return { status: response.status, payload, cookie: response.headers.get("set-cookie")?.split(";")[0] };
  }

  async function login(email, password) {
    const result = await call("/portal/auth/login", {
      method: "POST", body: { email, password },
    });
    assert.equal(result.status, 200, "synthetic test account should authenticate");
    assert.ok(result.cookie, "authenticated session cookie should be set");
    return result.cookie;
  }

  const portalUiUrl = process.env.SMH_PORTAL_UI_BASE ?? "http://127.0.0.1:80/support-portal/";
  const screenshotDirectory = join(
    fileURLToPath(new URL("../../../", import.meta.url)),
    "generated-artifacts",
    "portal-ui-e2e",
  );
  await mkdir(screenshotDirectory, { recursive: true });
  async function inspectSignedInUI(browser, role, email, password, expectedReportId) {
    await browser.clearCookies();
    await browser.navigate(portalUiUrl);
    await waitForBrowserValue(browser, "Boolean(document.querySelector('input[type=email]'))");
    const credentials = JSON.stringify({ email, password });
    const submitted = await browser.evaluate(`(() => {
      const data = ${credentials};
      const email = document.querySelector('input[type=email]');
      const password = document.querySelector('input[type=password]');
      const button = document.querySelector('[data-testid="button-sign-in"]');
      if (!email || !password || !button) return false;
      const set = (element, value) => {
        Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(element, value);
        element.dispatchEvent(new Event('input', { bubbles: true }));
        element.dispatchEvent(new Event('change', { bubbles: true }));
      };
      set(email, data.email);
      set(password, data.password);
      button.click();
      return true;
    })()`);
    assert.equal(submitted, true, "login controls must be present in the portal UI");
    await waitForBrowserValue(browser, "Boolean(document.querySelector('.portal-shell'))");
    const taskNavTestId = role === "agent" ? "link-my-tasks" : "link-staff-tasks";
    const expectedHeading = role === "agent" ? "My Tasks" : role === "manager" ? "Team Tasks" : "Staff Tasks";
    const openedTasks = await browser.evaluate(`(() => {
      const link = document.querySelector('[data-testid="${taskNavTestId}"]');
      if (!link) return false;
      link.click();
      return true;
    })()`);
    assert.equal(openedTasks, true, `${role} should have task navigation`);
    await waitForBrowserValue(browser, `document.querySelector('h1')?.innerText === ${JSON.stringify(expectedHeading)}`);
    await waitForBrowserValue(browser, "Boolean(document.querySelector('#submit-work'))");
    const advancedRequestsBeforeOpen = await browser.evaluate(`performance.getEntriesByType('resource')
      .map((entry) => entry.name)
      .filter((url) => url.includes('/api/portal/activity-reports') || url.includes('/api/portal/performance'))`);
    assert.deepEqual(advancedRequestsBeforeOpen, [], "collapsed advanced reports should not delay the main task view");
    const state = await browser.evaluate(`(() => ({
      hasStaffAccounts: Boolean(document.querySelector('[data-testid="link-staff-accounts"]')),
      hasStaffSection: Boolean(document.querySelector('[data-testid="link-staff"]') || document.querySelector('[data-testid="link-staff-accounts"]')),
      hasTaskCreation: Boolean(document.querySelector('[data-testid="button-open-create-task"]')),
      workerNavigation: ['link-my-tasks','link-my-support-cases','link-notifications','link-submit-work']
        .filter((testId) => Boolean(document.querySelector('[data-testid="' + testId + '"]'))),
      taskTitles: Array.from(document.querySelectorAll('.task-card h3')).map((item) => item.innerText),
      reportNoticeCount: document.querySelectorAll('[data-testid^="report-notice-"]').length,
      reportLinks: Array.from(document.querySelectorAll('[data-testid^="link-report-notice-"]')).map((item) => item.getAttribute('href')),
      reportCards: Array.from(document.querySelectorAll('.report-list .report-card')).map((item) => item.id),
    }))()`);
    await browser.screenshot(join(screenshotDirectory, `${role}.png`));
    if (expectedReportId) {
      await browser.evaluate("document.getElementById('advanced-reports').open = true; true");
      await waitForBrowserValue(browser, `Boolean(document.getElementById(${JSON.stringify(`report-${expectedReportId}`)}))`);
      await waitForBrowserValue(browser, "Boolean(document.querySelector('.performance-table tbody tr td')?.innerText.trim())");
      const advancedRequestsAfterOpen = await browser.evaluate(`performance.getEntriesByType('resource')
        .map((entry) => entry.name)
        .filter((url) => url.includes('/api/portal/activity-reports') || url.includes('/api/portal/performance'))`);
      assert.ok(advancedRequestsAfterOpen.some((url) => url.includes('/api/portal/activity-reports')));
      assert.ok(advancedRequestsAfterOpen.some((url) => url.includes('/api/portal/performance')));
      state.reportCards = await browser.evaluate("Array.from(document.querySelectorAll('.report-list .report-card')).map((item) => item.id)");
    }
    if (role === "owner") {
      await browser.evaluate(`document.querySelector('[data-testid="button-open-create-task"]')?.click()`);
      await waitForBrowserValue(browser, "Boolean(document.querySelector('.task-create-modal'))");
      const taskModal = await browser.evaluate(`(() => ({
        hasTitle: Boolean(document.querySelector('#task-title')),
        hasInstructions: Boolean(document.querySelector('#task-instructions')),
        hasWorker: Boolean(document.querySelector('#task-assignee')),
        hasPriority: Boolean(document.querySelector('#task-priority')),
        hasDeadline: Boolean(document.querySelector('#task-deadline')),
      }))()`);
      Object.assign(state, { taskModal });
      await browser.evaluate(`document.querySelector('.task-create-modal button[aria-label="Close"]')?.click()`);
      await waitForBrowserValue(browser, "Boolean(document.querySelector('[data-testid=\"button-open-create-task\"]'))");
    }
    if (role === "agent") {
      await browser.setViewport(402, 874);
      const phoneNav = await browser.evaluate(`(() => ({
        visible: getComputedStyle(document.querySelector('.mobile-nav')).display !== 'none',
        labels: Array.from(document.querySelectorAll('.mobile-nav-link span')).map((item) => item.innerText),
        viewportWidth: window.innerWidth,
      }))()`);
      Object.assign(state, { phoneNav });
      await browser.screenshot(join(screenshotDirectory, "agent-mobile.png"));
      await browser.setViewport(768, 1024);
      const tabletNavVisible = await browser.evaluate("getComputedStyle(document.querySelector('.mobile-nav')).display !== 'none'");
      Object.assign(state, { tabletNavVisible });
      await browser.evaluate("document.getElementById('advanced-reports').open = true; true");
      await waitForBrowserValue(browser, "Boolean(document.querySelector('.performance-table tbody tr td')?.innerText.trim())");
      const performanceRows = await browser.evaluate("Array.from(document.querySelectorAll('.performance-table tbody tr')).map((row) => Array.from(row.querySelectorAll('td')).map((cell) => cell.innerText))");
      Object.assign(state, { performanceRows });
    }
    if (role === "owner" || role === "manager") {
      const staffTestId = role === "owner" ? "link-staff-accounts" : "link-staff";
      const openedStaff = await browser.evaluate(`(() => {
        const link = document.querySelector('[data-testid="${staffTestId}"]');
        if (!link) return false;
        link.click();
        return true;
      })()`);
      assert.equal(openedStaff, true, `${role} should have the Staff section`);
      await waitForBrowserValue(browser, "document.querySelector('h1')?.innerText === 'Staff'");
      await waitForBrowserValue(browser, "Boolean(document.querySelector('[data-testid=\"staff-workload\"]'))");
      const staffWorkloadIds = await browser.evaluate(`Array.from(document.querySelectorAll('[data-testid^="staff-workload-"]')).map((item) => item.getAttribute('data-testid').replace('staff-workload-',''))`);
      Object.assign(state, {
        staffWorkloadIds,
        hasCreateStaffAccount: await browser.evaluate("Boolean(document.querySelector('[data-testid=\"button-create-staff\"]'))"),
      });
      await browser.screenshot(join(screenshotDirectory, `${role}-staff.png`));
    }
    return state;
  }

  async function ownerRequest(cookie, path, method, body) {
    const result = await call(path, { cookie, method, body });
    return result;
  }

  try {
    const created = new Date().toISOString();
    const seedClient = await pool.connect();
    try {
      await seedClient.query("BEGIN");
      for (const [id, email, name, password] of [
        [ownerId, ownerEmail, `E2E TEST ONLY Owner ${suffix}`, ownerPassword],
        [managerId, managerEmail, `E2E TEST ONLY Manager ${suffix}`, managerPassword],
        [agentId, `task-e2e-agent-${suffix}@example.invalid`, `E2E TEST ONLY Agent ${suffix}`, agentPassword],
        [outsideAgentId, `task-e2e-outside-${suffix}@example.invalid`, `E2E TEST ONLY Outside Agent ${suffix}`, outsidePassword],
      ]) {
        await seedClient.query(
          `INSERT INTO smh.portal_users
             (id,email,display_name,password_hash,role,active,must_change_password,created,updated)
           VALUES($1,$2,$3,$4,$5,TRUE,FALSE,$6,$6)`,
          [id, email, name, hashPassword(password), id === ownerId ? "admin" : "agent", created],
        );
      }
      await seedClient.query(
        "INSERT INTO smh.portal_manager_roles(staff_id,created) VALUES($1,$2)",
        [managerId, created],
      );
      for (const schema of ["smh", "smh_test"]) {
        if (schema === "smh_test") {
          await seedClient.query(
            `INSERT INTO ${schema}.portal_users
               (id,email,display_name,password_hash,role,active,must_change_password,created,updated)
             VALUES($1,$2,$3,$4,'agent',TRUE,FALSE,$5,$5)`,
            [agentId, `task-e2e-agent-${suffix}@support.invalid`, `E2E TEST ONLY Agent ${suffix}`,
              hashPassword(agentPassword), created],
          );
        }
        await seedClient.query(
          `INSERT INTO ${schema}.assistant_escalations
             (id,user_id,question,status,reply,created,updated,category,priority,workflow_status,assigned_staff_id)
           VALUES($1,$2,$3,'open','',$4,$4,'technical','normal','assigned',$5)`,
          [supportCaseIds[0], Number(Date.now()), "E2E TEST ONLY synthetic support request.", created, agentId],
        );
        await seedClient.query(
          `INSERT INTO ${schema}.assistant_support_replies
             (id,case_id,staff_id,responder_name,text,status,request_id,created,updated)
           VALUES($1,$2,$3,$4,$5,'sent',$6,$7,$7)`,
          [supportReplyIds[0], supportCaseIds[0], agentId, `E2E TEST ONLY Agent ${suffix}`,
            "E2E TEST ONLY stored reply; no Telegram delivery was attempted.", `e2e-reply-${suffix}`, created],
        );
      }
      await seedClient.query("COMMIT");
      seeded = true;
    } catch (error) {
      await seedClient.query("ROLLBACK");
      throw error;
    } finally {
      seedClient.release();
    }

    const ownerCookie = await login(ownerEmail, ownerPassword);
    const managerCookie = await login(managerEmail, managerPassword);
    const agentCookie = await login(`task-e2e-agent-${suffix}@example.invalid`, agentPassword);
    const outsideCookie = await login(`task-e2e-outside-${suffix}@example.invalid`, outsidePassword);

    const teamResponse = await ownerRequest(ownerCookie, "/portal/teams", "POST", {
      name: `E2E TEST ONLY ${suffix}`,
    });
    assert.equal(teamResponse.status, 201, JSON.stringify(teamResponse.payload));
    const teamId = teamResponse.payload.teamId;
    teamIds.push(teamId);
    const membership = await ownerRequest(ownerCookie, `/portal/teams/${teamId}/members`, "PUT", {
      members: [{ staffId: managerId, teamRole: "manager" }, { staffId: agentId, teamRole: "worker" }],
    });
    assert.equal(membership.status, 200, JSON.stringify(membership.payload));
    const reassignTeam = await ownerRequest(ownerCookie, "/portal/teams", "POST", {
      name: `E2E TEST ONLY reassignment ${suffix}`,
    });
    assert.equal(reassignTeam.status, 201, JSON.stringify(reassignTeam.payload));
    const reassignTeamId = reassignTeam.payload.teamId;
    teamIds.push(reassignTeamId);
    const reassignMembership = await ownerRequest(ownerCookie, `/portal/teams/${reassignTeamId}/members`, "PUT", {
      members: [{ staffId: outsideAgentId, teamRole: "worker" }],
    });
    assert.equal(reassignMembership.status, 200, JSON.stringify(reassignMembership.payload));

    const individualInput = {
      requestId: requestIds[0], title: `E2E TEST ONLY individual ${suffix}`,
      instructions: "Automated authenticated lifecycle verification; no customer or production data.",
      priority: "normal", effortPoints: 2, dueAt: null, teamId: null, assignedStaffId: agentId,
    };
    const individualCreate = await ownerRequest(ownerCookie, "/portal/tasks", "POST", individualInput);
    assert.equal(individualCreate.status, 201, JSON.stringify(individualCreate.payload));
    const individualTaskId = individualCreate.payload.taskId;
    taskIds.push(individualTaskId);
    const duplicateCreate = await ownerRequest(ownerCookie, "/portal/tasks", "POST", individualInput);
    assert.equal(duplicateCreate.status, 200, "duplicate request should return the existing task");
    assert.equal(duplicateCreate.payload.taskId, individualTaskId);

    const teamInput = {
      requestId: requestIds[1], title: `E2E TEST ONLY team ${suffix}`,
      instructions: "Automated team visibility and review verification; no customer or production data.",
      priority: "high", effortPoints: 3, dueAt: null, teamId, assignedStaffId: null,
    };
    const teamTaskCreate = await ownerRequest(ownerCookie, "/portal/tasks", "POST", teamInput);
    assert.equal(teamTaskCreate.status, 201, JSON.stringify(teamTaskCreate.payload));
    const teamTaskId = teamTaskCreate.payload.taskId;
    taskIds.push(teamTaskId);
    const reassignTaskCreate = await ownerRequest(ownerCookie, "/portal/tasks", "POST", {
      requestId: requestIds[2], title: `E2E TEST ONLY reassignment ${suffix}`,
      instructions: "Automated task reassignment test. No customer data.",
      priority: "normal", effortPoints: 1, dueAt: null, teamId, assignedStaffId: agentId,
    });
    assert.equal(reassignTaskCreate.status, 201, JSON.stringify(reassignTaskCreate.payload));
    const reassignTaskId = reassignTaskCreate.payload.taskId;
    taskIds.push(reassignTaskId);

    const teamTaskBeforeEdit = await call(`/portal/tasks/${teamTaskId}`, { cookie: ownerCookie });
    assert.equal(teamTaskBeforeEdit.status, 200);
    const dueSoon = new Date(Date.now() + 45 * 60_000).toISOString();
    const editInput = {
      expectedUpdatedAt: teamTaskBeforeEdit.payload.updated,
      title: `${teamTaskBeforeEdit.payload.title} edited`,
      instructions: teamTaskBeforeEdit.payload.instructions,
      priority: teamTaskBeforeEdit.payload.priority,
      effortPoints: 4,
      dueAt: dueSoon,
      teamId,
      assignedStaffId: null,
    };
    const editTask = await call(`/portal/tasks/${teamTaskId}`, {
      method: "PATCH", cookie: ownerCookie, body: editInput,
    });
    assert.equal(editTask.status, 200, JSON.stringify(editTask.payload));
    assert.equal(editTask.payload.effortPoints, 4);
    assert.ok(editTask.payload.events.some((event) => event.eventType === "task_edited"));
    const eventCountAfterEdit = editTask.payload.events.length;
    const duplicateEdit = await call(`/portal/tasks/${teamTaskId}`, {
      method: "PATCH", cookie: ownerCookie, body: editInput,
    });
    assert.equal(duplicateEdit.status, 200, "a duplicate edit tap should be idempotent");
    assert.equal(duplicateEdit.payload.events.length, eventCountAfterEdit, "duplicate edit must not duplicate audit history");
    const staleEdit = await call(`/portal/tasks/${teamTaskId}`, {
      method: "PATCH", cookie: ownerCookie, body: { ...editInput, title: "Stale overwrite attempt" },
    });
    assert.equal(staleEdit.status, 409, "stale edits must not overwrite newer changes");
    const agentEdit = await call(`/portal/tasks/${teamTaskId}`, {
      method: "PATCH", cookie: agentCookie, body: editInput,
    });
    assert.equal(agentEdit.status, 403, "agents must not edit or reassign tasks");
    const earlyReminders = await call("/portal/task-notifications", { cookie: agentCookie });
    assert.equal(earlyReminders.status, 200);
    assert.equal(earlyReminders.payload.notifications.filter(
      (notice) => notice.taskId === teamTaskId && notice.type === "deadline_approaching",
    ).length, 1, "an upcoming deadline should generate a persistent notice while the task is active");
    const duplicateEarlyReminders = await call("/portal/task-notifications", { cookie: agentCookie });
    assert.equal(duplicateEarlyReminders.payload.notifications.filter(
      (notice) => notice.taskId === teamTaskId && notice.type === "deadline_approaching",
    ).length, 1, "reopening notifications must not duplicate the reminder");
    const reassignmentSource = await call(`/portal/tasks/${reassignTaskId}`, { cookie: ownerCookie });
    assert.equal(reassignmentSource.status, 200);
    const reassigned = await call(`/portal/tasks/${reassignTaskId}`, {
      method: "PATCH", cookie: ownerCookie, body: {
        expectedUpdatedAt: reassignmentSource.payload.updated,
        title: reassignmentSource.payload.title,
        instructions: reassignmentSource.payload.instructions,
        priority: reassignmentSource.payload.priority,
        effortPoints: 2,
        dueAt: null,
        teamId: reassignTeamId,
        assignedStaffId: outsideAgentId,
      },
    });
    assert.equal(reassigned.status, 200, JSON.stringify(reassigned.payload));
    assert.equal(reassigned.payload.assignedStaffId, outsideAgentId, "owner reassignment should persist the new assignee");
    assert.ok(reassigned.payload.events.some((event) => event.eventType === "task_edited"));
    const oldAssigneeTask = await call(`/portal/tasks/${reassignTaskId}`, { cookie: agentCookie });
    assert.equal(oldAssigneeTask.status, 404, "the former assignee must lose task access after reassignment");
    const newAssigneeNotifications = await call("/portal/task-notifications", { cookie: outsideCookie });
    assert.ok(newAssigneeNotifications.payload.notifications.some(
      (notice) => notice.taskId === reassignTaskId && notice.type === "reassigned",
    ), "new assignee should receive a persistent reassignment notice");

    const forbiddenCreate = await ownerRequest(agentCookie, "/portal/tasks", "POST", {
      ...individualInput, requestId: `task-e2e-${suffix}-agent-forbidden`,
    });
    assert.equal(forbiddenCreate.status, 403, "agents must not create or assign tasks");
    const outsideTask = await call(`/portal/tasks/${teamTaskId}`, { cookie: outsideCookie });
    assert.equal(outsideTask.status, 404, "an agent outside the team must not read its task");
    const outsideTransition = await call(`/portal/tasks/${teamTaskId}/status`, {
      method: "PATCH", cookie: outsideCookie, body: { status: "accepted", note: "" },
    });
    assert.equal(outsideTransition.status, 404, "an agent outside the team must not change its task");

    const accept = await call(`/portal/tasks/${individualTaskId}/status`, {
      method: "PATCH", cookie: agentCookie, body: { status: "accepted", note: "" },
    });
    assert.equal(accept.status, 200);
    const duplicateAccept = await call(`/portal/tasks/${individualTaskId}/status`, {
      method: "PATCH", cookie: agentCookie, body: { status: "accepted", note: "" },
    });
    assert.equal(duplicateAccept.status, 200, "duplicate status tap should be idempotent");

    for (const [cookie, path, status, note, expected] of [
      [agentCookie, `/portal/tasks/${individualTaskId}/status`, "in_progress", "", 200],
      [agentCookie, `/portal/tasks/${individualTaskId}/status`, "submitted_for_review", "First submission for E2E review.", 200],
      [agentCookie, `/portal/tasks/${individualTaskId}/status`, "approved", "", 403],
      [ownerCookie, `/portal/tasks/${individualTaskId}/status`, "revision_requested", "E2E test revision: add a clearer completion note.", 200],
      [agentCookie, `/portal/tasks/${individualTaskId}/status`, "in_progress", "", 200],
      [agentCookie, `/portal/tasks/${individualTaskId}/status`, "submitted_for_review", "Resubmitted after the E2E revision.", 200],
      [ownerCookie, `/portal/tasks/${individualTaskId}/status`, "approved", "", 200],
    ]) {
      const result = await call(path, { method: "PATCH", cookie, body: { status, note } });
      assert.equal(result.status, expected, `${status} should return ${expected}; got ${result.status}`);
    }

    for (const [status, note, cookie, expected] of [
      ["accepted", "", agentCookie, 200],
      ["in_progress", "", agentCookie, 200],
      ["submitted_for_review", "Team task submitted for test review.", agentCookie, 200],
      ["approved", "", agentCookie, 403],
      ["approved", "", ownerCookie, 200],
    ]) {
      const result = await call(`/portal/tasks/${teamTaskId}/status`, {
        method: "PATCH", cookie, body: { status, note },
      });
      assert.equal(result.status, expected, `team task ${status} should return ${expected}; got ${result.status}`);
    }

    const detail = await call(`/portal/tasks/${individualTaskId}`, { cookie: ownerCookie });
    assert.equal(detail.status, 200);
    assert.equal(detail.payload.status, "approved");
    assert.ok(detail.payload.events.some((event) => event.newValue === "revision_requested" && event.feedback.includes("E2E test revision")));
    assert.ok(detail.payload.events.some((event) => event.newValue === "approved"));

    const agentNotifications = await call("/portal/task-notifications", { cookie: agentCookie });
    assert.equal(agentNotifications.status, 200);
    const assignedNotifications = agentNotifications.payload.notifications.filter(
      (notice) => taskIds.slice(0, 2).includes(notice.taskId) && notice.type === "assigned",
    );
    assert.equal(assignedNotifications.length, 2, "assignment retry must not duplicate assignment notifications");
    const revisionNotification = agentNotifications.payload.notifications.find(
      (notice) => notice.taskId === individualTaskId && notice.type === "revision_requested",
    );
    assert.ok(revisionNotification, "revision notification should persist for the assigned agent");
    const marked = await call(`/portal/task-notifications/${revisionNotification.notificationId}/read`, {
      method: "PATCH", cookie: agentCookie,
    });
    const markedAgain = await call(`/portal/task-notifications/${revisionNotification.notificationId}/read`, {
      method: "PATCH", cookie: agentCookie,
    });
    assert.equal(marked.status, 200);
    assert.equal(markedAgain.status, 200);
    assert.equal(markedAgain.payload.readAt, marked.payload.readAt, "mark-read retry should be idempotent");
    const reminders = agentNotifications.payload.notifications.filter(
      (notice) => notice.taskId === teamTaskId && notice.type === "deadline_approaching",
    );
    assert.equal(reminders.length, 1, "a deadline approaching within 24 hours should create one persistent notice");
    const remindersAgain = await call("/portal/task-notifications", { cookie: agentCookie });
    assert.equal(remindersAgain.payload.notifications.filter(
      (notice) => notice.taskId === teamTaskId && notice.type === "deadline_approaching",
    ).length, 1, "deadline reminder polling must not create duplicates");

    const today = new Date().toISOString().slice(0, 10);
    const reportInput = {
      period: "daily", periodStart: today,
      completedWork: "E2E TEST ONLY: completed assigned verification task.",
      outstandingWork: "E2E TEST ONLY: no work outstanding.",
      blockers: "E2E TEST ONLY: none.", plans: "E2E TEST ONLY: close test run.",
    };
    const submittedReport = await call("/portal/activity-reports", {
      method: "POST", cookie: agentCookie, body: reportInput,
    });
    assert.equal(submittedReport.status, 201, JSON.stringify(submittedReport.payload));
    const reportId = submittedReport.payload.reportId;
    reportIds.push(reportId);
    const duplicateReport = await call("/portal/activity-reports", {
      method: "POST", cookie: agentCookie, body: reportInput,
    });
    assert.equal(duplicateReport.status, 200, "duplicate report submission should return the saved report");
    assert.equal(duplicateReport.payload.reportId, reportId);
    const outsideReport = await call("/portal/activity-reports", {
      method: "POST", cookie: outsideCookie,
      body: { ...reportInput, completedWork: "E2E TEST ONLY: another team's report." },
    });
    assert.equal(outsideReport.status, 201);
    reportIds.push(outsideReport.payload.reportId);
    const managerCannotReviewOutsideReport = await call(
      `/portal/activity-reports/${outsideReport.payload.reportId}/review`,
      { method: "PATCH", cookie: managerCookie, body: { status: "reviewed", note: "E2E TEST ONLY: unauthorized review." } },
    );
    assert.equal(managerCannotReviewOutsideReport.status, 404,
      "manager must not review a report outside their authorized team");
    const agentReviewAttempt = await call(`/portal/activity-reports/${reportId}/review`, {
      method: "PATCH", cookie: agentCookie, body: { status: "reviewed", note: "Unauthorized self review" },
    });
    assert.equal(agentReviewAttempt.status, 403, "agents must not review reports");
    const reportRevision = await call(`/portal/activity-reports/${reportId}/review`, {
      method: "PATCH", cookie: ownerCookie, body: { status: "revision_requested", note: "E2E TEST ONLY: clarify the completed work." },
    });
    assert.equal(reportRevision.status, 200);
    const revisionInbox = await call("/portal/report-notifications", { cookie: agentCookie });
    const revisionNotice = revisionInbox.payload.notifications.find(
      (notice) => notice.reportId === reportId && notice.outcome === "revision_requested",
    );
    assert.ok(revisionNotice, "revision outcome should notify the report author");
    assert.equal(revisionNotice.period, "daily");
    assert.equal(revisionNotice.periodStart, today);
    assert.equal(revisionNotice.reviewerFeedback, "E2E TEST ONLY: clarify the completed work.");
    assert.equal(revisionNotice.href, `/tasks#report-${encodeURIComponent(reportId)}`);
    assert.equal(Object.hasOwn(revisionNotice, "reviewerId"), false);
    assert.equal(Object.hasOwn(revisionNotice, "reviewerName"), false);
    const ownerCannotReadWorkerNotice = await call(
      `/portal/report-notifications/${revisionNotice.notificationId}/read`,
      { method: "PATCH", cookie: ownerCookie },
    );
    assert.equal(ownerCannotReadWorkerNotice.status, 404, "notifications must be scoped to their recipient");
    const revisionInboxAgain = await call("/portal/report-notifications", { cookie: agentCookie });
    assert.equal(revisionInboxAgain.payload.notifications.filter(
      (notice) => notice.reportId === reportId && notice.outcome === "revision_requested",
    ).length, 1, "re-fetching a notice must not create duplicates");
    const resubmission = await call("/portal/activity-reports", {
      method: "POST", cookie: agentCookie,
      body: { ...reportInput, completedWork: "E2E TEST ONLY: clarified completed work." },
    });
    assert.equal(resubmission.status, 200);
    assert.equal(resubmission.payload.reviewStatus, "submitted");
    assert.ok(resubmission.payload.events.some((event) => event.eventType === "resubmitted"));
    const reportApproval = await call(`/portal/activity-reports/${reportId}/review`, {
      method: "PATCH", cookie: ownerCookie, body: { status: "reviewed", note: "E2E TEST ONLY: report complete." },
    });
    assert.equal(reportApproval.status, 200);
    assert.equal(reportApproval.payload.reviewStatus, "reviewed");
    const approvalInbox = await call("/portal/report-notifications", { cookie: agentCookie });
    const dailyNotices = approvalInbox.payload.notifications.filter((notice) => notice.reportId === reportId);
    assert.equal(dailyNotices.length, 2, "revision and approval should each have one persistent notification");
    assert.ok(dailyNotices.some((notice) => notice.outcome === "approved"
      && notice.reviewerFeedback === "E2E TEST ONLY: report complete."));
    assert.equal(dailyNotices.find((notice) => notice.outcome === "approved")?.period, "daily");
    const duplicateApproval = await call(`/portal/activity-reports/${reportId}/review`, {
      method: "PATCH", cookie: ownerCookie, body: { status: "reviewed", note: "E2E TEST ONLY: duplicate tap." },
    });
    assert.equal(duplicateApproval.status, 409, "a repeated review tap must not make a second outcome");
    const approvedNotice = dailyNotices.find((notice) => notice.outcome === "approved");
    const markReportNoticeRead = await call(
      `/portal/report-notifications/${approvedNotice.notificationId}/read`,
      { method: "PATCH", cookie: agentCookie },
    );
    const markReportNoticeReadAgain = await call(
      `/portal/report-notifications/${approvedNotice.notificationId}/read`,
      { method: "PATCH", cookie: agentCookie },
    );
    assert.equal(markReportNoticeRead.status, 200);
    assert.equal(markReportNoticeReadAgain.status, 200);
    assert.equal(markReportNoticeReadAgain.payload.readAt, markReportNoticeRead.payload.readAt,
      "marking the same notice read twice must be idempotent");
    const weekStart = new Date();
    weekStart.setUTCDate(weekStart.getUTCDate() - ((weekStart.getUTCDay() + 6) % 7));
    const weekDate = weekStart.toISOString().slice(0, 10);
    const invalidWeekDate = new Date(weekStart);
    invalidWeekDate.setUTCDate(invalidWeekDate.getUTCDate() + 1);
    const invalidWeeklyReport = await call("/portal/activity-reports", {
      method: "POST", cookie: agentCookie,
      body: { ...reportInput, period: "weekly", periodStart: invalidWeekDate.toISOString().slice(0, 10) },
    });
    assert.equal(invalidWeeklyReport.status, 400, "weekly report must start on Monday");
    const weeklyReport = await call("/portal/activity-reports", {
      method: "POST", cookie: agentCookie,
      body: { ...reportInput, period: "weekly", periodStart: weekDate, completedWork: "E2E TEST ONLY: weekly summary." },
    });
    assert.equal(weeklyReport.status, 201, JSON.stringify(weeklyReport.payload));
    reportIds.push(weeklyReport.payload.reportId);
    const weeklyRevision = await call(`/portal/activity-reports/${weeklyReport.payload.reportId}/review`, {
      method: "PATCH", cookie: ownerCookie, body: { status: "revision_requested", note: "E2E TEST ONLY: add one completed-work detail." },
    });
    assert.equal(weeklyRevision.status, 200);
    const weeklyRevisionInbox = await call("/portal/report-notifications", { cookie: agentCookie });
    assert.equal(weeklyRevisionInbox.payload.notifications.filter(
      (notice) => notice.reportId === weeklyReport.payload.reportId && notice.outcome === "revision_requested",
    ).length, 1, "weekly revision should notify the report author once");
    const weeklyResubmission = await call("/portal/activity-reports", {
      method: "POST", cookie: agentCookie,
      body: { ...reportInput, period: "weekly", periodStart: weekDate, completedWork: "E2E TEST ONLY: weekly summary with added detail." },
    });
    assert.equal(weeklyResubmission.status, 200);
    assert.ok(weeklyResubmission.payload.events.some((event) => event.eventType === "resubmitted"));
    const weeklyReview = await call(`/portal/activity-reports/${weeklyReport.payload.reportId}/review`, {
      method: "PATCH", cookie: ownerCookie, body: { status: "reviewed", note: "E2E TEST ONLY: weekly review complete." },
    });
    assert.equal(weeklyReview.status, 200);
    const weeklyInbox = await call("/portal/report-notifications", { cookie: agentCookie });
    const weeklyNotices = weeklyInbox.payload.notifications.filter((notice) => notice.reportId === weeklyReport.payload.reportId);
    assert.equal(weeklyNotices.length, 2);
    assert.ok(weeklyNotices.some((notice) => notice.outcome === "approved"
      && notice.reviewerFeedback === "E2E TEST ONLY: weekly review complete."));
    const reportList = await call("/portal/activity-reports", { cookie: agentCookie });
    assert.ok(reportList.payload.reports.some((report) => report.reportId === reportId));
    assert.ok(reportList.payload.reports.some((report) => report.reportId === weeklyReport.payload.reportId));
    const authorReport = reportList.payload.reports.find((report) => report.reportId === reportId);
    assert.equal(authorReport.reviewedByName, null, "workers must not see private reviewer identity");
    assert.ok(authorReport.events.filter((event) => ["reviewed", "revision_requested"].includes(event.eventType))
      .every((event) => event.actorName === "Authorized reviewer"),
    "review history should use a generic reviewer label for workers");
    const performance = await call("/portal/performance", { cookie: ownerCookie });
    assert.equal(performance.status, 200, JSON.stringify(performance.payload));
    const agentMetric = performance.payload.metrics.find((metric) => metric.staffId === agentId);
    assert.ok(agentMetric, "owner performance should include the synthetic agent");
    assert.ok(agentMetric.supportCases >= 1, "synthetic support case should produce a nonzero case metric");
    assert.ok(agentMetric.supportReplies >= 1, "synthetic stored reply should produce a nonzero reply metric");
    const managerTasks = await call("/portal/tasks", { cookie: managerCookie });
    assert.equal(managerTasks.status, 200);
    assert.ok(managerTasks.payload.tasks.some((task) => task.taskId === teamTaskId),
      "manager should see a task in their authorized team");
    assert.ok(!managerTasks.payload.tasks.some((task) => task.taskId === reassignTaskId),
      "manager must not see another team's task");
    const managerStaffCreation = await call("/portal/staff", { method: "POST", cookie: managerCookie, body: {} });
    const agentStaffCreation = await call("/portal/staff", { method: "POST", cookie: agentCookie, body: {} });
    assert.equal(managerStaffCreation.status, 403, "managers must not create portal staff accounts");
    assert.equal(agentStaffCreation.status, 403, "agents must not create portal staff accounts");

    const browser = await startBrowser();
    try {
      const ownerUi = await inspectSignedInUI(browser, "owner", ownerEmail, ownerPassword, reportId);
      assert.equal(ownerUi.hasStaffAccounts, true, "owner UI should expose staff account management");
      assert.equal(ownerUi.hasTaskCreation, true, "owner UI should expose task creation");
      assert.equal(ownerUi.hasStaffSection, true, "owner UI should expose the Staff section");
      assert.equal(ownerUi.hasCreateStaffAccount, true, "owner Staff section should retain staff-account controls");
      assert.deepEqual(ownerUi.taskModal, {
        hasTitle: true, hasInstructions: true, hasWorker: true, hasPriority: true, hasDeadline: true,
      }, "the simple task form should contain the requested fields");
      assert.ok(ownerUi.staffWorkloadIds.includes(agentId), "owner Staff section should show the worker workload");
      assert.ok(!ownerUi.staffWorkloadIds.includes(managerId), "manager accounts should not be counted as workers");

      const managerUi = await inspectSignedInUI(browser, "manager", managerEmail, managerPassword, reportId);
      assert.equal(managerUi.hasStaffAccounts, false, "manager UI must hide owner staff controls");
      assert.equal(managerUi.hasTaskCreation, false, "manager UI must hide owner task creation");
      assert.equal(managerUi.hasStaffSection, true, "manager UI should expose the scoped Staff section");
      assert.equal(managerUi.hasCreateStaffAccount, false, "manager must not see owner account controls");
      assert.ok(managerUi.staffWorkloadIds.includes(agentId), "manager Staff section should show their authorized worker");
      assert.ok(!managerUi.staffWorkloadIds.includes(outsideAgentId), "manager Staff section must hide an unauthorized worker");
      assert.ok(managerUi.taskTitles.some((title) => title.includes("team")),
        "manager UI should show work from the manager's authorized team");
      assert.ok(!managerUi.taskTitles.some((title) => title.includes("reassign")),
        "manager UI must not show another team's task");
      assert.ok(managerUi.reportCards.includes(`report-${reportId}`),
        "authorized manager should see their team's activity report");

      const agentUi = await inspectSignedInUI(browser, "agent", `task-e2e-agent-${suffix}@example.invalid`, agentPassword, reportId);
      assert.equal(agentUi.hasStaffAccounts, false, "agent UI must hide owner staff controls");
      assert.equal(agentUi.hasTaskCreation, false, "agent UI must hide owner task creation");
      assert.equal(agentUi.hasStaffSection, false, "agent UI must hide the Staff section");
      assert.deepEqual(agentUi.workerNavigation.sort(), [
        "link-my-support-cases", "link-my-tasks", "link-notifications", "link-submit-work",
      ], "worker navigation should contain only their work, cases and notifications");
      assert.deepEqual(agentUi.phoneNav.labels, ["My Tasks", "My Support Cases", "Notifications", "Submit Work"],
        "mobile navigation should show readable worker destinations");
      assert.equal(agentUi.phoneNav.visible, true, "worker navigation should be visible on an iPhone-sized viewport");
      assert.equal(agentUi.tabletNavVisible, true, "worker navigation should be visible on an iPad-sized viewport");
      assert.ok(agentUi.taskTitles.some((title) => title.includes("individual")));
      assert.ok(!agentUi.taskTitles.some((title) => title.includes("reassign")),
        "agent UI must not show another team's task");
      assert.equal(agentUi.reportNoticeCount, 4, "worker UI should show each approval and revision outcome");
      assert.ok(agentUi.reportLinks.some((href) => href === `/tasks#report-${encodeURIComponent(reportId)}`),
        "notification link should point to the specific report");
      assert.ok(agentUi.reportCards.includes(`report-${reportId}`),
        "report notification target should exist in the rendered report list");
      const reportHref = `/tasks#report-${encodeURIComponent(reportId)}`;
      const clickedReportLink = await browser.evaluate(`(() => {
        const link = document.querySelector('a[href=${JSON.stringify(reportHref)}]');
        if (!link) return false;
        link.click();
        return true;
      })()`);
      assert.equal(clickedReportLink, true, "report update should be clickable");
      const scrolledToReport = await waitForBrowserValue(
        browser,
        `(() => {
          const target = document.getElementById(${JSON.stringify(`report-${reportId}`)});
          return Boolean(target && target.getBoundingClientRect().top < window.innerHeight);
        })()`,
      );
      assert.equal(scrolledToReport, true, "notification link should scroll the exact report into view");
      const agentMetricRow = agentUi.performanceRows.find((row) => row[0]?.includes(`E2E TEST ONLY Agent ${suffix}`));
      assert.ok(agentMetricRow, `authenticated agent UI should show its own workload row; rows=${JSON.stringify(agentUi.performanceRows)}`);
      assert.match(agentMetricRow.at(-2) ?? "", /[1-9]\d* total · [0-9]\d* open/,
        "authenticated agent UI should show the synthetic support case metric");
      assert.ok(Number(agentMetricRow.at(-1)) >= 1,
        "authenticated agent UI should show the sent-reply metric");
      console.log(`Authenticated UI evidence: owner, manager, and agent checked; phone/tablet navigation checked; screenshots saved under generated-artifacts/portal-ui-e2e.`);
    } finally {
      await browser.close();
    }

    const persisted = await pool.query(
      `SELECT t.id,t.status,
              (SELECT count(*)::int FROM smh.staff_task_events e WHERE e.task_id=t.id) AS event_count,
              (SELECT count(*)::int FROM smh.staff_task_notifications n WHERE n.task_id=t.id) AS notice_count
         FROM smh.staff_tasks t
        WHERE t.id=ANY($1::text[]) ORDER BY t.id`,
      [taskIds.slice(0, 2)],
    );
    assert.equal(persisted.rows.length, 2, "both tasks should be persisted");
    assert.ok(persisted.rows.every((row) => row.status === "approved"), "approved status should survive a fresh DB read");
    assert.ok(persisted.rows.every((row) => Number(row.event_count) >= 6), "task history should persist every lifecycle action");
    assert.ok(persisted.rows.every((row) => Number(row.notice_count) >= 2), "assignment and review notifications should persist");
    const reassignPersisted = await pool.query(
      `SELECT t.assigned_staff_id,t.team_id,
              (SELECT count(*)::int FROM smh.staff_task_events e WHERE e.task_id=t.id) AS event_count
         FROM smh.staff_tasks t WHERE t.id=$1`,
      [reassignTaskId],
    );
    assert.equal(reassignPersisted.rows[0]?.assigned_staff_id, outsideAgentId);
    assert.equal(reassignPersisted.rows[0]?.team_id, reassignTeamId);
    assert.ok(Number(reassignPersisted.rows[0]?.event_count) >= 2);
    const reportPersisted = await pool.query(
      `SELECT r.review_status,
              (SELECT count(*)::int FROM smh.staff_activity_report_events e WHERE e.report_id=r.id) AS event_count,
              (SELECT count(*)::int FROM smh.staff_report_notifications n WHERE n.report_id=r.id) AS notification_count
         FROM smh.staff_activity_reports r WHERE r.id=$1`,
      [reportId],
    );
    assert.equal(reportPersisted.rows[0]?.review_status, "reviewed", "final report decision should persist");
    assert.ok(Number(reportPersisted.rows[0]?.event_count) >= 4, "submission, revision, resubmission, and review history should persist");
    assert.equal(Number(reportPersisted.rows[0]?.notification_count), 2, "one report notification should persist per review outcome");
  } finally {
    if (seeded) {
      const client = await pool.connect();
      try {
        await client.query("BEGIN");
        for (const schema of ["smh", "smh_test"]) {
          await client.query(
            `DELETE FROM ${schema}.assistant_support_replies WHERE id=ANY($1::text[])`,
            [supportReplyIds],
          );
          await client.query(
            `DELETE FROM ${schema}.assistant_escalations WHERE id=ANY($1::text[])`,
            [supportCaseIds],
          );
          if (schema === "smh_test") {
            await client.query(`DELETE FROM ${schema}.portal_users WHERE id=$1`, [agentId]);
          }
        }
        await client.query(
          `DELETE FROM smh.portal_audit
            WHERE actor_id=ANY($1::text[]) OR entity_id=ANY($2::text[])`,
          [userIds, [...userIds, ...teamIds, ...taskIds, ...reportIds]],
        );
        await client.query("DELETE FROM smh.staff_activity_reports WHERE id=ANY($1::text[])", [reportIds]);
        await client.query(
          `DELETE FROM smh.staff_tasks
            WHERE id=ANY($1::text[]) OR (created_by=ANY($2::text[]) AND request_id=ANY($3::text[]))`,
          [taskIds, userIds, requestIds],
        );
        await client.query("DELETE FROM smh.staff_teams WHERE id=ANY($1::text[])", [teamIds]);
        await client.query("DELETE FROM smh.portal_sessions WHERE staff_id=ANY($1::text[])", [userIds]);
        await client.query("DELETE FROM smh.portal_manager_roles WHERE staff_id=ANY($1::text[])", [userIds]);
        await client.query("DELETE FROM smh.portal_users WHERE id=ANY($1::text[])", [userIds]);
        const remaining = await client.query(
          `SELECT (SELECT count(*)::int FROM smh.portal_users WHERE id=ANY($1::text[])) AS users,
                  (SELECT count(*)::int FROM smh.staff_tasks WHERE id=ANY($2::text[])) AS tasks,
                  (SELECT count(*)::int FROM smh.staff_teams WHERE id=ANY($3::text[])) AS teams,
                  (SELECT count(*)::int FROM smh.staff_activity_reports WHERE id=ANY($4::text[])) AS reports,
                  (SELECT count(*)::int FROM smh.staff_task_events WHERE task_id=ANY($2::text[])) AS task_events,
                  (SELECT count(*)::int FROM smh.staff_task_notifications WHERE task_id=ANY($2::text[])) AS notifications,
                  (SELECT count(*)::int FROM smh.staff_activity_report_events WHERE report_id=ANY($4::text[])) AS report_events,
                   (SELECT count(*)::int FROM smh.staff_report_notifications WHERE report_id=ANY($4::text[])) AS report_notifications,
                   (SELECT count(*)::int FROM smh.assistant_escalations WHERE id=ANY($6::text[])) AS support_cases,
                   (SELECT count(*)::int FROM smh.assistant_support_replies WHERE id=ANY($7::text[])) AS support_replies,
                   (SELECT count(*)::int FROM smh_test.assistant_escalations WHERE id=ANY($6::text[])) AS test_support_cases,
                   (SELECT count(*)::int FROM smh_test.assistant_support_replies WHERE id=ANY($7::text[])) AS test_support_replies,
                   (SELECT count(*)::int FROM smh_test.portal_users WHERE id=$8) AS test_support_user,
                  (SELECT count(*)::int FROM smh.portal_audit WHERE actor_id=ANY($1::text[]) OR entity_id=ANY($5::text[])) AS audit_events`,
          [userIds, taskIds, teamIds, reportIds, [...userIds, ...teamIds, ...taskIds, ...reportIds],
            supportCaseIds, supportReplyIds, agentId],
        );
        assert.equal(Object.values(remaining.rows[0]).reduce((total, value) => total + Number(value), 0), 0,
          "cleanup must remove only records created by this E2E run");
        await client.query("COMMIT");
      } catch (error) {
        await client.query("ROLLBACK");
        throw error;
      } finally {
        client.release();
      }
    }
    await pool.end();
  }
});
