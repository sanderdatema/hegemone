import { describe, it, expect } from "vitest";
import {
  attachableFilesFromFileList,
  attachableFilesFromTransfer,
  imageFilesFromFileList,
  imageFilesFromTransfer,
  removeImageMarkdown,
  insertIntoDrafts,
} from "./drawerImages.js";

function fakeFile(name, type) {
  return { name, type };
}

describe("imageFilesFromFileList", () => {
  it("laat alleen afbeeldingsbestanden door", () => {
    const files = [
      fakeFile("foo.png", "image/png"),
      fakeFile("bar.pdf", "application/pdf"),
      fakeFile("baz.jpg", "image/jpeg"),
    ];
    expect(imageFilesFromFileList(files).map((f) => f.name)).toEqual([
      "foo.png",
      "baz.jpg",
    ]);
  });

  it("geeft een lege array terug zonder input", () => {
    expect(imageFilesFromFileList(null)).toEqual([]);
    expect(imageFilesFromFileList(undefined)).toEqual([]);
  });

  it("negeert bestanden zonder (of leeg) type-veld", () => {
    const files = [fakeFile("noext", ""), fakeFile("photo.heic", "image/heic")];
    expect(imageFilesFromFileList(files).map((f) => f.name)).toEqual(["photo.heic"]);
  });

  it("werkt ook met een FileList-achtig (iterable) object", () => {
    const fileListLike = {
      0: fakeFile("a.png", "image/png"),
      1: fakeFile("b.txt", "text/plain"),
      length: 2,
      [Symbol.iterator]: function* () {
        yield this[0];
        yield this[1];
      },
    };
    expect(imageFilesFromFileList(fileListLike).map((f) => f.name)).toEqual(["a.png"]);
  });
});

describe("imageFilesFromTransfer", () => {
  it("geeft een lege array zonder transfer-object", () => {
    expect(imageFilesFromTransfer(null)).toEqual([]);
  });

  it("gebruikt .files als die afbeeldingen bevat", () => {
    const dt = { files: [fakeFile("a.png", "image/png"), fakeFile("b.txt", "text/plain")] };
    expect(imageFilesFromTransfer(dt).map((f) => f.name)).toEqual(["a.png"]);
  });

  it("valt terug op .items (plakken) als er geen files zijn", () => {
    const png = fakeFile("pasted.png", "image/png");
    const dt = {
      files: [],
      items: [
        { kind: "file", type: "image/png", getAsFile: () => png },
        { kind: "string", type: "text/plain", getAsFile: () => null },
      ],
    };
    expect(imageFilesFromTransfer(dt)).toEqual([png]);
  });

  it("negeert non-file items en null getAsFile", () => {
    const dt = {
      files: [],
      items: [
        { kind: "file", type: "application/pdf", getAsFile: () => fakeFile("x.pdf", "application/pdf") },
        { kind: "file", type: "image/png", getAsFile: () => null },
      ],
    };
    expect(imageFilesFromTransfer(dt)).toEqual([]);
  });
});

describe("removeImageMarkdown", () => {
  it("verwijdert de exacte markdown-image-referentie", () => {
    const text = "Hoi\n\n![foo.png](http://x/foo.png)\n\ntot ziens";
    expect(removeImageMarkdown(text, "foo.png", "http://x/foo.png")).toBe(
      "Hoi\n\ntot ziens"
    );
  });

  it("collapse't overtollige lege regels en trimt", () => {
    const text = "![a.png](u)\n\n\n\nrest";
    expect(removeImageMarkdown(text, "a.png", "u")).toBe("rest");
  });

  it("laat tekst ongemoeid als de referentie ontbreekt", () => {
    expect(removeImageMarkdown("gewoon tekst", "a.png", "u")).toBe("gewoon tekst");
  });

  it("is veilig met lege input", () => {
    expect(removeImageMarkdown(null, "a", "b")).toBe("");
  });
});


// --- Bredere whitelist (BETON-374) ---------------------------------------

describe("attachableFilesFromFileList", () => {
  it("laat afbeeldingen, tekst, JSON en PDF door", () => {
    const files = [
      { name: "a.png", type: "image/png" },
      { name: "b.txt", type: "text/plain" },
      { name: "c.json", type: "application/json" },
      { name: "d.pdf", type: "application/pdf" },
    ];
    expect(attachableFilesFromFileList(files)).toHaveLength(4);
  });

  it("herkent een .log die de browser als octet-stream aanbiedt", () => {
    const files = [{ name: "server.log", type: "application/octet-stream" }];
    expect(attachableFilesFromFileList(files)).toHaveLength(1);
  });

  it("laat een binair bestand liggen", () => {
    const files = [{ name: "tool.exe", type: "application/octet-stream" }];
    expect(attachableFilesFromFileList(files)).toEqual([]);
  });

  it("gaat om met leeg/ontbrekend", () => {
    expect(attachableFilesFromFileList(null)).toEqual([]);
    expect(attachableFilesFromFileList([])).toEqual([]);
  });
});

describe("attachableFilesFromTransfer", () => {
  it("valt terug op items als files leeg is (plakken)", () => {
    const file = { name: "notitie.md", type: "text/markdown" };
    const dt = {
      files: [],
      items: [{ kind: "file", type: "text/markdown", getAsFile: () => file }],
    };
    expect(attachableFilesFromTransfer(dt)).toEqual([file]);
  });

  it("negeert niet-toegestane items", () => {
    const dt = {
      files: [],
      items: [
        { kind: "file", type: "application/octet-stream", getAsFile: () => ({ name: "x.bin" }) },
      ],
    };
    expect(attachableFilesFromTransfer(dt)).toEqual([]);
  });
});

// BETON-403: het bewerken van een bestaande reactie had géén eigen doel —
// slepen/plakken daar deed niets, want er was geen derde tak naast
// "desc"/"comment" die naar editCommentText schrijft. De discriminerende
// eis is niet alleen "editComment wordt gevuld", maar ook "de andere twee
// velden blijven exact ongewijzigd" — een regressie die "editComment" per
// ongeluk naar commentText laat schrijven (de plan-gewaarschuwde fout) faalt
// anders niet op een test die alleen het geraakte veld controleert.
describe("insertIntoDrafts", () => {
  const drafts = () => ({ desc: "D", comment: "C", editComment: "E" });

  it("vult de omschrijving en laat comment/editComment ongewijzigd", () => {
    const next = insertIntoDrafts("desc", drafts(), 1, "!");
    expect(next).toEqual({ desc: "D!", comment: "C", editComment: "E" });
  });

  it("vult de nieuwe-reactie-composer en laat desc/editComment ongewijzigd", () => {
    const next = insertIntoDrafts("comment", drafts(), 1, "!");
    expect(next).toEqual({ desc: "D", comment: "C!", editComment: "E" });
  });

  it("vult een reactie in bewerkmodus en laat desc/comment ongewijzigd", () => {
    const next = insertIntoDrafts("editComment", drafts(), 1, "!");
    expect(next).toEqual({ desc: "D", comment: "C", editComment: "E!" });
  });

  // BETON-434: plakken in het antwoordveld van een vraag (nieuw antwoord én
  // antwoord wijzigen) deed niets — er was geen tak voor die velden.
  it("vult het antwoordveld van een vraag en laat de rest ongewijzigd", () => {
    const next = insertIntoDrafts("answer", { ...drafts(), answer: "A", editAnswer: "W" }, 1, "!");
    expect(next).toEqual({ desc: "D", comment: "C", editComment: "E", answer: "A!", editAnswer: "W" });
  });

  it("vult een antwoord in bewerkmodus en laat de rest ongewijzigd", () => {
    const next = insertIntoDrafts("editAnswer", { ...drafts(), answer: "A", editAnswer: "W" }, 1, "!");
    expect(next).toEqual({ desc: "D", comment: "C", editComment: "E", answer: "A", editAnswer: "W!" });
  });

  it("valt terug op de nieuwe-reactie-composer bij een onbekend doel", () => {
    expect(insertIntoDrafts("iets-anders", drafts(), 1, "!")).toEqual({
      desc: "D",
      comment: "C!",
      editComment: "E",
    });
  });

  it("voegt in aan het eind zonder caretpositie", () => {
    expect(insertIntoDrafts("editComment", drafts(), null, "!")).toEqual({
      desc: "D",
      comment: "C",
      editComment: "E!",
    });
  });
});
