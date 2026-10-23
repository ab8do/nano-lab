# Adding the desktop app to your existing repository

Copy these into your repository folder (keep your existing files):

- `app/`                              the whole folder
- `.github/workflows/build-app.yml`   the build workflow
- `documentation/app.md`              documentation

Then make four small edits by hand:

1. `.github/workflows/ci.yml`: change `python -m compileall -q software` to `python -m compileall -q software app`
2. `.gitignore`: append the contents of `gitignore-additions.txt`
3. `README.md`: before "## 9. Limitations and threats to validity" paste:

   ### 8.1 Desktop app (no installation)

   Instead of installing Python and libraries, download the ready-made app from the **Releases** page (Windows or Linux), unzip it and run `NanoLab`. A control panel opens in the browser (English, Français, العربية): choose the port and a project, press **Start**; the matching firmware is uploaded to the Nano automatically when the project changes. Details, security notes and the build pipeline: [documentation/app.md](documentation/app.md).

4. `CHANGELOG.md`: add at the top:

   ## 1.1.0
   - Desktop app (`app/`): one control panel for Dino, Gesture Games and Robo; automatic firmware upload when the project changes; live camera preview; token meter; EN/FR/AR interface; CI builds Windows and Linux packages with all libraries, the uploader and the hand model bundled.

Commit and push. Then on GitHub: Actions -> "Build desktop app" -> Run workflow. When it finishes, download the artifact (NanoLab-windows or NanoLab-linux). For a public download page create a release by pushing a tag:

    git tag v1.1.0 && git push origin v1.1.0
