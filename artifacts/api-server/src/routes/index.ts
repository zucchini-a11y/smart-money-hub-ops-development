import { Router, type IRouter } from "express";
import healthRouter from "./health";
import supportRouter from "./support";

const router: IRouter = Router();

router.use(healthRouter);
router.use(supportRouter);

export default router;
