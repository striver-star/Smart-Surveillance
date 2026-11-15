/* Sample data for console pages whose services aren't built yet (site map: Phase 5).
   Every page that uses it shows a "Preview" banner. Nothing here is site data. */
"use strict";
window.PREVIEW = {
  map: {
    title: "Sample site plan",
    buildings: [
      { name: "Main gate", x: 40, y: 250, w: 70, h: 40 },
      { name: "Admin block", x: 170, y: 60, w: 150, h: 80 },
      { name: "Institute", x: 380, y: 50, w: 190, h: 110 },
      { name: "Restaurant", x: 190, y: 200, w: 120, h: 70 },
      { name: "Blocks 1–6", x: 380, y: 210, w: 200, h: 100 },
      { name: "Stores", x: 640, y: 80, w: 110, h: 70 },
    ],
    zones: [
      { name: "Perimeter fence (armed 18:00–06:00)", points: "20,20 780,20 780,380 20,380", kind: "fence" },
      { name: "Store yard (restricted)", points: "620,60 770,60 770,180 620,180", kind: "restricted" },
    ],
    cameras: [
      { name: "Main gate entrance", x: 70, y: 235, state: "ok" }, { name: "Main gate exit", x: 95, y: 300, state: "ok" },
      { name: "Admin reception", x: 245, y: 150, state: "ok" }, { name: "Institute corridor", x: 470, y: 170, state: "ok" },
      { name: "Restaurant", x: 250, y: 285, state: "warn" }, { name: "Store out 1", x: 700, y: 165, state: "ok" },
      { name: "Block 2 up left", x: 420, y: 325, state: "bad" }, { name: "Stream fence", x: 760, y: 300, state: "ok" },
    ],
    guards: [{ name: "Patrol 1", x: 330, y: 330 }, { name: "Patrol 2", x: 600, y: 200 }],
  },
};
