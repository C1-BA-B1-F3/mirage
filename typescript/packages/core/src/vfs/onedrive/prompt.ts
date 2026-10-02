export const PROMPT = `{prefix}
  Remote OneDrive / SharePoint document library. Maps driveItem paths to virtual paths.
  IMPORTANT: This is a remote mount. Prefer targeted reads (grep, head) over full scans. Avoid cat on large files without piping to head/tail.
  Supports: ls, cat, head, tail, grep, rg, wc, find, tree, jq, stat.
  File versions are retained, snapshots pin and read prior versions.`
