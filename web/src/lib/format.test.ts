import { NOW } from "../test/factories";
import { dayLabel, fileExtension, formatBytes, formatChatListTime, formatClock, formatDuration, previewLabel, sameDay } from "./format";

const DAY = 86_400_000;

describe("dates", () => {
  it("chat list: time today, Yesterday, weekday this week, numeric date otherwise", () => {
    expect(formatChatListTime(NOW - 3_600_000, NOW)).toBe(formatClock(NOW - 3_600_000));
    expect(formatChatListTime(NOW - DAY, NOW)).toBe("Yesterday");
    expect(formatChatListTime(NOW - 3 * DAY, NOW)).toBe("Tuesday"); // 2026-11-24
    expect(formatChatListTime(NOW - 10 * DAY, NOW)).toBe("11/17/2026");
    expect(formatChatListTime(NOW - 400 * DAY, NOW)).toMatch(/\/\d{4}$/);
  });
  it("divider labels", () => {
    expect(dayLabel(NOW, NOW)).toBe("Today");
    expect(dayLabel(NOW - DAY, NOW)).toBe("Yesterday");
    expect(dayLabel(NOW - 2 * DAY, NOW)).toBe("Wednesday");
    expect(dayLabel(NOW - 30 * DAY, NOW)).toBe("10/28/2026");
  });
  it("midnight boundary uses calendar days, not 24h windows", () => {
    const justAfterMidnight = Date.UTC(2026, 10, 27, 0, 5);
    const justBefore = Date.UTC(2026, 10, 26, 23, 55);
    expect(dayLabel(justBefore, justAfterMidnight)).toBe("Yesterday");
    expect(sameDay(justBefore, justAfterMidnight)).toBe(false);
  });
});

describe("sizes and durations", () => {
  it("formats bytes", () => {
    expect(formatBytes(null)).toBe("");
    expect(formatBytes(512)).toBe("512 B");
    expect(formatBytes(1536)).toBe("1.5 KB");
    expect(formatBytes(15 * 1024 * 1024)).toBe("15 MB");
    expect(formatBytes(5 * 1024 ** 4)).toBe("5.0 TB");
  });
  it("formats durations defensively", () => {
    expect(formatDuration(3)).toBe("0:03");
    expect(formatDuration(75.9)).toBe("1:15");
    expect(formatDuration(3725)).toBe("1:02:05");
    for (const bad of [null, NaN, -1, Infinity]) expect(formatDuration(bad)).toBe("0:00");
  });
});

describe("labels", () => {
  it("file extensions", () => {
    expect(fileExtension("report.pdf", null)).toBe("PDF");
    expect(fileExtension(null, "application/zip")).toBe("ZIP");
    expect(fileExtension(null, null)).toBe("FILE");
  });
  it("preview labels", () => {
    expect(previewLabel("ptt", null)).toBe("Voice message");
    expect(previewLabel("image", "caption")).toBe("caption");
    expect(previewLabel("weird", null)).toBe("");
  });
});
