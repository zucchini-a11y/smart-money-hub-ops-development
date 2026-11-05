const allowedDuringPasswordSetup = new Set([
  "GET /portal/auth/session",
  "POST /portal/auth/password",
  "POST /portal/auth/logout",
]);

export function isAllowedDuringPasswordSetup(method: string, routePath: string): boolean {
  const normalizedPath = routePath.replace(/^\/api(?=\/)/, "").replace(/\/+$/, "") || "/";
  return allowedDuringPasswordSetup.has(`${method.toUpperCase()} ${normalizedPath}`);
}
