import React from "react";
const paths = {
  overview: "M3 3h7v7H3z M14 3h7v7h-7z M3 14h7v7H3z M14 14h7v7h-7z",
  twitch: "M5 3h16v12l-6 6h-4v-4H5V3z M10 7v6 M16 7v6",
  queue: "M8 6h13 M8 12h13 M8 18h13 M3 6h.01 M3 12h.01 M3 18h.01",
  clips:
    "m9 8 7 4-7 4V8z M4 3h16a1 1 0 0 1 1 1v16a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1z",
  settings:
    "m9 3-1 3-3 1 1 3-2 2 2 2-1 3 3 1 1 3h4l1-3 3-1-1-3 2-2-2-2 1-3-3-1-1-3H9z M12 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6",
  plus: "M12 5v14 M5 12h14",
  upload: "M12 16V3 m-5 5 5-5 5 5 M4 15v5h16v-5",
  file: "M6 3h8l4 4v14H6V3z M14 3v5h4 M9 13h6 M9 17h4",
  chevron: "m9 5 7 7-7 7",
  arrow: "M5 12h14 m-5-5 5 5-5 5",
  refresh: "M20 7v5h-5 M4 17v-5h5 M6 6a8 8 0 0 1 13 3 M5 15a8 8 0 0 0 13 3",
  close: "m6 6 12 12 M6 18 18 6",
  pause: "M8 5v14 M16 5v14",
  play: "m8 4 12 8-12 8V4z",
  terminal: "m5 7 4 5-4 5 M12 17h7",
  download: "M12 3v12 m-5-5 5 5 5-5 M4 17v4h16v-4",
  stop: "M6 6h12v12H6z",
  check: "m5 12 4 4L19 6",
  clock: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18 M12 7v5l3 2",
  chip: "M6 6h12v12H6z M9 9h6v6H9z M9 2v4 M15 2v4 M9 18v4 M15 18v4 M2 9h4 M2 15h4 M18 9h4 M18 15h4",
  info: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18 M12 11v6 M12 7h.01",
  trash: "M3 6h18 M9 6V3h6v3 M6 6l1 15h10l1-15 M10 10v7 M14 10v7",
  folder: "M3 6h7l2 2h9v12H3V6z",
  record:
    "M12 5a7 7 0 1 0 0 14 7 7 0 0 0 0-14 M12 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6",
  external: "M14 3h7v7 M21 3 10 14 M10 4H4v16h16v-6",
  filter: "M3 5h18 M6 12h12 M9 19h6",
};
export function Icon({ name }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.65"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d={paths[name] || paths.file} />
    </svg>
  );
}
