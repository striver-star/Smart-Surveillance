/* Sample data for console pages whose services aren't built yet (maps: Phase 5, reports: Phase 6).
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
  reports: {
    week: [["Mon", 31], ["Tue", 24], ["Wed", 42], ["Thu", 18], ["Fri", 37], ["Sat", 12], ["Sun", 9]],
    list: [
      { name: "Daily security report", period: "Yesterday", sent: "08:05 by WhatsApp", to: "CSO, IT Manager", status: "delivered" },
      { name: "Weekly summary", period: "Last week", sent: "Monday 08:05", to: "GM, CSO", status: "delivered" },
      { name: "Monthly management report", period: "October", sent: "1 November 08:05", to: "GM", status: "read" },
      { name: "Device health report", period: "Last 7 days", sent: "Monday 08:10", to: "IT Manager", status: "delivered" },
    ],
    top: [["Perimeter fence", 64], ["Store yard", 21], ["Main gate (after hours)", 14], ["Restaurant back door", 9]],
  },
};
