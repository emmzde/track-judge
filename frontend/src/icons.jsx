import React from "react";

const interfaceMarks = {
  spectrum: <path d="M2 10v2m4-5v8m4-12v14m4-10v8m4-5v2" />,
  report: (
    <path d="M5 2h6l4 4v11a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V2Z M11 2v4h4 M8 10h4m-4 4h4" />
  ),
  security: (
    <path d="M10 2.5 16.5 5v4.5c0 3.7-2.6 6.4-6.5 8-3.9-1.6-6.5-4.3-6.5-8V5L10 2.5Z M7.5 10l1.7 1.7 3.5-3.5" />
  ),
  language: (
    <>
      <circle cx="10" cy="10" r="7.5" />
      <ellipse cx="10" cy="10" rx="3.3" ry="7.5" />
      <path d="M2.5 10h15" />
    </>
  ),
};

const windowMarks = {
  minimize: "M4 8h8",
  maximize: "M4 4h8v8H4z",
  restore: "M6.5 4H12v5.5 M4 6.5h5.5V12H4z",
  close: "m4.5 4.5 7 7m0-7-7 7",
};

export function InterfaceIcon({ name }) {
  return (
    <svg
      aria-hidden="true"
      focusable="false"
      viewBox="0 0 20 20"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      {interfaceMarks[name]}
    </svg>
  );
}

export function WindowIcon({ name }) {
  return (
    <svg
      aria-hidden="true"
      focusable="false"
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d={windowMarks[name]} />
    </svg>
  );
}
