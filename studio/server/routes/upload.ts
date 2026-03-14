import { Router, Request, Response } from "express";
import multer from "multer";
import path from "path";
import { existsSync, mkdirSync } from "fs";
import { requireProjectRoot } from "../lib/project.js";

const router = Router();

function getUploadMiddleware() {
  const root = requireProjectRoot();
  const importsDir = path.join(root, "imports");
  if (!existsSync(importsDir)) {
    mkdirSync(importsDir, { recursive: true });
  }

  const storage = multer.diskStorage({
    destination: (_req, _file, cb) => {
      cb(null, importsDir);
    },
    filename: (_req, file, cb) => {
      const timestamp = Date.now();
      const safeName = file.originalname.replace(/[^a-zA-Z0-9._-]/g, "_");
      cb(null, `${timestamp}_${safeName}`);
    },
  });

  return multer({ storage, limits: { fileSize: 2 * 1024 * 1024 * 1024 } });
}

router.post("/upload", (req: Request, res: Response) => {
  const upload = getUploadMiddleware();
  upload.single("file")(req, res, (err) => {
    if (err) {
      res.status(500).json({ error: err instanceof Error ? err.message : "Upload failed" });
      return;
    }
    if (!req.file) {
      res.status(400).json({ error: "No file uploaded" });
      return;
    }

    const root = requireProjectRoot();
    const relativePath = path.relative(root, req.file.path);

    res.json({
      ok: true,
      path: relativePath,
      filename: req.file.originalname,
      size: req.file.size,
    });
  });
});

export default router;
