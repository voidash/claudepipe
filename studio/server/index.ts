import express from "express";
import manifestRoutes from "./routes/manifest.js";
import mediaRoutes from "./routes/media.js";
import uploadRoutes from "./routes/upload.js";
import filesystemRoutes from "./routes/filesystem.js";
import projectRoutes from "./routes/project.js";
import { projectRoot, isImportMode } from "./lib/project.js";

const app = express();
const PORT = parseInt(process.env.PORT || "3001", 10);

app.use(express.json({ limit: "50mb" }));

// Mode endpoint — tells the frontend which mode we're in
app.get("/api/mode", (_req, res) => {
  res.json({
    mode: isImportMode ? "import" : "studio",
    project_root: projectRoot,
    cwd: process.cwd(),
  });
});

// Always available — filesystem browsing and project creation
app.use("/api", filesystemRoutes);
app.use("/api", projectRoutes);

// Only available when PROJECT_ROOT is set (studio mode)
if (!isImportMode) {
  app.use("/api", manifestRoutes);
  app.use("/api", mediaRoutes);
  app.use("/api", uploadRoutes);
}

app.listen(PORT, () => {
  console.log(`claudepipe studio server on :${PORT}`);
  if (isImportMode) {
    console.log("Mode: IMPORT (no PROJECT_ROOT set)");
    console.log(`CWD: ${process.cwd()}`);
  } else {
    console.log(`Mode: STUDIO`);
    console.log(`PROJECT_ROOT: ${projectRoot}`);
  }
});
