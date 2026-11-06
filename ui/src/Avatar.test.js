import { describe, it, expect } from "vitest";
import { render } from "svelte/server";
import Avatar from "./Avatar.svelte";

// Server-side render (svelte/server) werkt in de node-omgeving zonder DOM/jsdom.

describe("Avatar", () => {
  it("rendert een <img> als avatarUrl gezet is", () => {
    const { body } = render(Avatar, {
      props: { handle: "person", avatarUrl: "/api/v1/users/person/avatar?v=abcd1234" },
    });
    expect(body).toContain("<img");
    expect(body).toContain("/api/v1/users/person/avatar?v=abcd1234");
  });

  it("valt terug op initialen zonder avatarUrl", () => {
    const { body } = render(Avatar, { props: { handle: "person" } });
    expect(body).not.toContain("<img");
    // Initialen van "person".
    expect(body).toContain("PE");
  });
});
