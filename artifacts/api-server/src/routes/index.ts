import { Router, type IRouter } from "express";
import healthRouter from "./health";
import authRouter from "./auth";
import supportRouter from "./support";
import portalRouter from "./portal";
import portalApplicantControlsRouter from "./portal-applicant-controls";
import educationVideosRouter from "./education-videos";
import memberRouter from "./member";
import websiteSupportRouter from "./website-support";
import { requirePasswordReady, requirePortalSession } from "../lib/portal-auth";

const router: IRouter = Router();

router.use(healthRouter);
router.use(authRouter);
router.use(memberRouter);
router.use(supportRouter);
router.use(portalRouter);
router.use(websiteSupportRouter);
router.use(
  "/portal",
  requirePortalSession,
  requirePasswordReady,
  portalApplicantControlsRouter,
);
router.use(educationVideosRouter);

export default router;
