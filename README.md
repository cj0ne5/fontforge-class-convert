# Batch Convert Illustrator Files to FontForge

Inspired by <https://github.com/fontpixel/font-template>, and
extended for classroom use.

All students should upload their illustrator files to subdirectories in a shared google folder. Eg:

```
Shared_Folder/
|
|-Student_a/
| |-33 exclam.svg
| |-(more svg files)
|
|-Student_b/
  |-33 exclam.svg
  |-(more svg files)
```

This script will download all of the contents from Google Drive, create one new `otf`/`sfd` file pair per subdirectory, and upload to the respective subdirectory.

It will also do some cleanup:

- Merge each stroke per svg into a single character
- Generate kerning tables
- Add zero-width characters for whitespace (eg CR, LF)

To run:

- Install FontForge (I used Brew - if you don't already have FontForge, the executable will prompt you to install via Brew)
- Download this repo
- Upload a `credentials.json` from Google Cloud Admin
- Double-click `sync_drive.command` to run