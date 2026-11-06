import { describe, it, expect } from "vitest";
import { attachmentMarkdown, isImageAttachment } from "./attachments.js";

describe("attachmentMarkdown", () => {
  it("bouwt een markdown-image-referentie uit filename en url", () => {
    const att = {
      filename: "foto.png",
      url: "/api/v1/attachments/abc123",
      content_type: "image/png",
    };
    expect(attachmentMarkdown(att)).toBe("![foto.png](/api/v1/attachments/abc123)");
  });

  it("linkt een niet-afbeelding i.p.v. hem in te bedden (BETON-374)", () => {
    const att = {
      filename: "server.log",
      url: "/api/v1/attachments/abc123",
      content_type: "text/plain",
    };
    expect(attachmentMarkdown(att)).toBe("[server.log](/api/v1/attachments/abc123)");
  });

  it("zonder content_type geldt een attachment niet als afbeelding", () => {
    expect(isImageAttachment({})).toBe(false);
    expect(isImageAttachment({ content_type: "image/webp" })).toBe(true);
    expect(isImageAttachment(null)).toBe(false);
  });

  it("gaat om met filenames die markdown-tekens bevatten", () => {
    const att = {
      filename: "screen [1].png",
      url: "/api/v1/attachments/def456",
      content_type: "image/png",
    };
    expect(attachmentMarkdown(att)).toBe("![screen [1].png](/api/v1/attachments/def456)");
  });
});
