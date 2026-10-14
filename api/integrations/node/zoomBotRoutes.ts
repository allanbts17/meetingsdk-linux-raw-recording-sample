/* eslint-disable max-len, require-jsdoc, valid-jsdoc */
import {Router as createRouter, Request, Response, NextFunction} from "express";
import * as admin from "firebase-admin";
import {zoomBotRequest, ZoomBotError} from "../services/zoomBotService";

type Verify = (token: string) => Promise<{uid: string}>;

/** Firebase identity plus an explicit allowlist, checked on every request. */
export function authorizeZoomBot(
  verify: Verify = (token) => admin.auth().verifyIdToken(token, true),
) {
  return async (req: Request, res: Response, next: NextFunction): Promise<void> => {
    res.setHeader("Cache-Control", "no-store");
    const allowed = new Set((process.env.ZOOM_BOT_ALLOWED_UIDS || "")
      .split(",").map((uid) => uid.trim()).filter(Boolean));
    if (!allowed.size) {
      res.status(503).json({error: {code: "ZOOM_BOT_AUTH_NOT_CONFIGURED"}});
      return;
    }
    const match = /^Bearer ([^\s]+)$/i.exec(req.get("Authorization") || "");
    if (!match) {
      res.status(401).json({error: {code: "UNAUTHENTICATED"}});
      return;
    }
    let identity;
    try {
      identity = await verify(match[1]);
    } catch {
      res.status(401).json({error: {code: "UNAUTHENTICATED"}});
      return;
    }
    if (!allowed.has(identity.uid)) {
      res.status(403).json({error: {code: "FORBIDDEN"}});
      return;
    }
    next();
  };
}

const router = createRouter();
router.use(authorizeZoomBot());
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function forward(method: "GET" | "POST" | "DELETE", route: string) {
  return async (req: Request, res: Response): Promise<void> => {
    let path = route;
    for (const name of ["bot_id", "operation_id"]) {
      if (path.includes(":" + name)) {
        const value = req.params[name];
        if (typeof value !== "string" || !uuid.test(value)) {
          res.status(400).json({error: {code: "INVALID_ID"}});
          return;
        }
        path = path.replace(":" + name, value);
      }
    }
    const query = new URLSearchParams();
    for (const name of ["limit", "cursor", "status", "after_sequence"]) {
      const value = req.query[name];
      if (value !== undefined) {
        if (typeof value !== "string") {
          res.status(400).json({error: {code: "INVALID_QUERY"}});
          return;
        }
        query.set(name, value);
      }
    }
    if (query.size) path += "?" + query.toString();
    try {
      const reply = await zoomBotRequest(method, path,
        method === "POST" ? req.body : undefined, req.get("Idempotency-Key"));
      res.status(reply.status).json(reply.data);
    } catch (error: unknown) {
      const safe = error instanceof ZoomBotError ? error : new ZoomBotError(503, "ZOOM_BOT_UNAVAILABLE");
      res.status(safe.status).json({error: {code: safe.code}});
    }
  };
}

router.get("/capacity", forward("GET", "/v1/capacity"));
router.get("/bots", forward("GET", "/v1/bots"));
router.post("/bots", forward("POST", "/v1/bots"));
router.get("/bots/:bot_id", forward("GET", "/v1/bots/:bot_id"));
router.delete("/bots/:bot_id", forward("DELETE", "/v1/bots/:bot_id"));
router.get("/bots/:bot_id/events", forward("GET", "/v1/bots/:bot_id/events"));
router.get("/operations/:operation_id", forward("GET", "/v1/operations/:operation_id"));
for (const action of ["play", "pause", "resume", "stop"]) {
  router.post("/bots/:bot_id/" + action, forward("POST", "/v1/bots/:bot_id/" + action));
}
export default router;
