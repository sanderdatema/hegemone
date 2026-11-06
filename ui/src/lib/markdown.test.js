import { describe, it, expect } from "vitest";
import { renderMarkdown, renderWikiMarkdown } from "./markdown.js";

describe("renderWikiMarkdown — markdown-it basis (BETON-127/129)", () => {
  it("rendert koppen H1–H6 volledig, zonder offset (BETON-129)", () => {
    expect(renderWikiMarkdown("# Titel")).toBe("<h1>Titel</h1>");
    expect(renderWikiMarkdown("## Sub")).toBe("<h2>Sub</h2>");
    expect(renderWikiMarkdown("### Dieper")).toBe("<h3>Dieper</h3>");
    expect(renderWikiMarkdown("#### Nog")).toBe("<h4>Nog</h4>");
    expect(renderWikiMarkdown("##### En")).toBe("<h5>En</h5>");
    expect(renderWikiMarkdown("###### Kleinste")).toBe("<h6>Kleinste</h6>");
  });

  it("rendert GFM-tabellen met thead/tbody (BETON-127)", () => {
    const html = renderWikiMarkdown("| A | B |\n|---|---|\n| 1 | 2 |");
    expect(html).toContain("<table>");
    expect(html).toContain("<thead>");
    expect(html).toContain("<th>A</th>");
    expect(html).toContain("<th>B</th>");
    expect(html).toContain("<tbody>");
    expect(html).toContain("<td>1</td>");
    expect(html).toContain("<td>2</td>");
  });

  it("rendert vet, cursief en inline code", () => {
    const html = renderWikiMarkdown("**vet** en *cursief* en `code`");
    expect(html).toContain("<strong>vet</strong>");
    expect(html).toContain("<em>cursief</em>");
    expect(html).toContain("<code>code</code>");
  });

  it("rendert ongeordende en geordende lijsten", () => {
    expect(renderWikiMarkdown("- een\n- twee")).toContain("<ul>");
    expect(renderWikiMarkdown("- een\n- twee")).toContain("<li>een</li>");
    expect(renderWikiMarkdown("1. een\n2. twee")).toContain("<ol>");
  });

  it("rendert codeblokken zonder er ticketrefs in te linken", () => {
    const html = renderWikiMarkdown("```\nBETON-91\n```", [], ["BETON"]);
    expect(html).toContain("<pre><code>");
    expect(html).not.toContain("data-ticket");
    expect(html).toContain("BETON-91");
  });

  it("rendert blockquotes en horizontale lijnen", () => {
    expect(renderWikiMarkdown("> citaat")).toContain("<blockquote>");
    expect(renderWikiMarkdown("> citaat")).toContain("citaat");
    expect(renderWikiMarkdown("---")).toBe("<hr>");
  });

  it("escaped HTML (geen XSS)", () => {
    expect(renderWikiMarkdown("<script>alert(1)</script>")).toContain(
      "&lt;script&gt;"
    );
    expect(renderWikiMarkdown("<script>alert(1)</script>")).not.toContain("<script>");
  });
});

describe("renderWikiMarkdown — veilige URLs (BETON-5)", () => {
  it("staat http(s) en absolute-pad-links toe", () => {
    expect(renderWikiMarkdown("[ok](https://x.nl)")).toContain(
      'href="https://x.nl"'
    );
    expect(renderWikiMarkdown("[ok](/pad)")).toContain('href="/pad"');
  });

  it("weigert javascript: en data:-links (letterlijk of veilig genegeerd)", () => {
    const jsHtml = renderWikiMarkdown("[nee](javascript:alert(1))");
    expect(jsHtml).not.toContain('href="javascript:');
    const dataHtml = renderWikiMarkdown("[nee](data:text/html,evil)");
    expect(dataHtml).not.toContain('href="data:');
  });

  it("linkt een niet-afbeelding-bijlage naar de attachment-serve (BETON-374)", () => {
    // `attachmentMarkdown` maakt hier `[naam](url)` van; dat moet echt een <a>
    // worden, anders staat de markdown als platte tekst in de omschrijving.
    const html = renderMarkdown("[server.log](/api/v1/attachments/abc)");
    expect(html).toContain('href="/api/v1/attachments/abc"');
    expect(html).toContain("server.log");
  });

  it("rendert afbeeldingen met veilige URL (attachment-serve of http)", () => {
    expect(renderWikiMarkdown("![kat](/api/v1/attachments/abc)")).toContain(
      '<img src="/api/v1/attachments/abc"'
    );
    expect(renderWikiMarkdown("![x](https://x.nl/p.png)")).toContain(
      '<img src="https://x.nl/p.png"'
    );
  });

  it("weigert onveilige image-URLs", () => {
    const html = renderWikiMarkdown("![x](javascript:alert(1))");
    expect(html).not.toContain('src="javascript:');
  });
});

describe("renderWikiMarkdown — wiki-interlinks (BETON-25/57)", () => {
  it("zet [[slug]] om naar een wikilink-anker met data-wiki", () => {
    const html = renderWikiMarkdown("zie [[deploy-gotchas]]");
    expect(html).toContain('data-wiki="deploy-gotchas"');
    expect(html).toContain(">deploy-gotchas</a>");
  });

  it("negeert niet-slug-achtige [[..]] (geen injectie)", () => {
    const html = renderWikiMarkdown("[[Niet Geldig]]");
    expect(html).not.toContain("data-wiki");
  });

  it("markeert een dode link als knownRefs is meegegeven (kaal → huidige scope)", () => {
    // knownRefs zijn gekwalificeerde keys "<scope> <slug>"; currentScope default "global".
    const html = renderWikiMarkdown("[[bestaat]] en [[weg]]", ["global bestaat"]);
    expect(html).toContain('data-wiki="bestaat"');
    expect(html).not.toContain('data-wiki="bestaat" data-wiki-scope="global" data-wiki-dead');
    expect(html).toContain('data-wiki="weg" data-wiki-scope="global" data-wiki-dead="true"');
    expect(html).toContain("wikilink-dead");
  });

  it("markeert niets als dood zonder knownRefs (backward-compat)", () => {
    const html = renderWikiMarkdown("[[wat-dan-ook]]");
    expect(html).not.toContain("wikilink-dead");
    expect(html).not.toContain("data-wiki-dead");
  });

  it("cross-scope: [[BETON:slug]] rendert levend als de ref in BETON bestaat (BETON-306)", () => {
    const html = renderWikiMarkdown("zie [[BETON:deploy]]", ["BETON deploy"], [], "global");
    expect(html).toContain('data-wiki="deploy" data-wiki-scope="BETON"');
    expect(html).not.toContain("data-wiki-dead");
    expect(html).toContain(">BETON:deploy</a>"); // qualifier zichtbaar in het label
  });

  it("cross-scope: dezelfde slug in twee scopes — de qualifier bepaalt levend/dood", () => {
    // Alleen global:x bestaat. [[BETON:x]] is dus dood, [[global:x]] leeft.
    const html = renderWikiMarkdown("[[BETON:x]] en [[global:x]]", ["global x"], [], "global");
    expect(html).toContain('data-wiki="x" data-wiki-scope="BETON" data-wiki-dead="true"');
    expect(html).toContain('data-wiki="x" data-wiki-scope="global" role="link"');
    expect(html).not.toContain('data-wiki="x" data-wiki-scope="global" data-wiki-dead');
  });

  it("kale link in een projectscope resolveert naar dat project", () => {
    const html = renderWikiMarkdown("[[foo]]", ["BETON foo"], [], "BETON");
    expect(html).toContain('data-wiki="foo" data-wiki-scope="BETON"');
    expect(html).not.toContain("data-wiki-dead");
  });

  // De gemelde bug (BETON-306): in de praktijk is élke link kaal geschreven,
  // dus de qualifier-syntax alléén repareerde Persons wiki niet.
  it("kale link vanuit global naar een uniek project rendert LEVEND", () => {
    const html = renderWikiMarkdown(
      "zie [[bt-cli-afschaffing]]",
      ["BETON bt-cli-afschaffing"],
      [],
      "global",
    );
    expect(html).toContain('data-wiki="bt-cli-afschaffing" data-wiki-scope="BETON"');
    expect(html).not.toContain("data-wiki-dead");
    // Label blijft zoals geschreven; de scope-sprong staat in de tooltip.
    expect(html).toContain(">bt-cli-afschaffing</a>");
    expect(html).toContain('title="BETON: bt-cli-afschaffing"');
  });

  it("kale link vanuit een project valt terug op global (global wint van een ander project)", () => {
    const html = renderWikiMarkdown(
      "[[ticket-werkwijze]]",
      ["global ticket-werkwijze", "BRAND ticket-werkwijze"],
      [],
      "BETON",
    );
    expect(html).toContain('data-wiki="ticket-werkwijze" data-wiki-scope="global"');
    expect(html).not.toContain("data-wiki-dead");
  });

  it("een lokale pagina wint van een gelijknamige elders (geen ongewenste sprong)", () => {
    const html = renderWikiMarkdown("[[x]]", ["BETON x", "global x"], [], "BETON");
    expect(html).toContain('data-wiki="x" data-wiki-scope="BETON"');
    expect(html).not.toContain("title="); // geen scope-sprong → geen tooltip
  });

  it("blijft dood bij meerdere kandidaat-projecten (ambigu → kwalificeer zelf)", () => {
    const html = renderWikiMarkdown("[[x]]", ["BETON x", "BRAND x"], [], "global");
    expect(html).toContain('data-wiki="x" data-wiki-scope="global" data-wiki-dead="true"');
  });
});

describe("renderWikiMarkdown — alias-syntax [[slug|tekst]] (BETON-346)", () => {
  it("toont de aliastekst als label, het doel blijft de slug", () => {
    const html = renderWikiMarkdown(
      "[[plan-field-tickets|field-based expected_action]]",
      ["BETON plan-field-tickets"],
      [],
      "BETON",
    );
    expect(html).toContain('data-wiki="plan-field-tickets" data-wiki-scope="BETON"');
    expect(html).not.toContain("data-wiki-dead");
    expect(html).toContain(">field-based expected_action</a>");
    expect(html).not.toContain(">plan-field-tickets</a>");
  });

  it("een alias krijgt altijd een title met de echte bestemming", () => {
    const html = renderWikiMarkdown("[[deploy|Zo deploy je]]", ["BETON deploy"], [], "BETON");
    expect(html).toContain('title="BETON: deploy"');
  });

  it("werkt samen met een scope-qualifier — label = alias, doel = qualifier:slug", () => {
    const html = renderWikiMarkdown(
      "[[BETON:deploy|Deploy-stappen]]",
      ["BETON deploy"],
      [],
      "global",
    );
    expect(html).toContain('data-wiki="deploy" data-wiki-scope="BETON"');
    expect(html).toContain(">Deploy-stappen</a>");
    expect(html).toContain('title="BETON: deploy"');
  });

  it("een dode aliaslink krijgt geen title (dood is al het signaal)", () => {
    const html = renderWikiMarkdown("[[weg|Ergens heen]]", ["BETON iets-anders"], [], "global");
    expect(html).toContain("data-wiki-dead=\"true\"");
    expect(html).not.toContain("title=");
  });

  it("zonder alias verandert er niets aan een gewone qualifier-link (geen overbodige title)", () => {
    const html = renderWikiMarkdown("[[BETON:deploy]]", ["BETON deploy"], [], "global");
    expect(html).toContain(">BETON:deploy</a>");
    expect(html).not.toContain("title=");
  });

  it("laat een lege of ontbrekende alias ongemoeid (backward-compat met de kale link)", () => {
    const html = renderWikiMarkdown("[[deploy]]", ["global deploy"], [], "global");
    expect(html).toContain(">deploy</a>");
    expect(html).not.toContain("title=");
  });

  it("een alias met HTML-onveilige tekens breekt niet uit het anker (geen injectie)", () => {
    // renderWikiMarkdown matcht ná markdown-it's HTML-escaping, dus "<"/">"/
    // "&"/'"' in de aliastekst staan al als entity tegen de tijd dat deze
    // functie ze ziet — rechtstreeks in de HTML zetten is dus veilig.
    const html = renderWikiMarkdown('[[deploy|<script>alert(1)</script> & "quotes"]]', [
      "global deploy",
    ]);
    expect(html).not.toContain("<script>");
    expect(html).toContain("&lt;script&gt;");
    expect(html).toContain("&amp;");
    expect(html).toContain("&quot;quotes&quot;");
  });
});

describe("renderWikiMarkdown — ticketref-linkificatie (BETON-106/107)", () => {
  it("linkificeert ticketrefs met een bekende project-key", () => {
    const html = renderWikiMarkdown("zie BETON-91 en SOS-3", [], ["BETON", "SOS"]);
    expect(html).toContain('data-ticket="BETON-91"');
    expect(html).toContain('data-ticket="SOS-3"');
    expect(html).toContain('class="ticketlink"');
  });

  it("linkificeert geen ref met een onbekende project-key", () => {
    const html = renderWikiMarkdown("zie COVID-19", [], ["BETON"]);
    expect(html).not.toContain("data-ticket");
  });

  it("linkificeert geen ticketref zonder knownProjectKeys (backward-compat)", () => {
    const html = renderWikiMarkdown("zie BETON-91");
    expect(html).not.toContain("data-ticket");
  });

  it("linkificeert plain-tekst-refs wel, codeblok-refs niet", () => {
    const inCode = renderWikiMarkdown("```\nBETON-91\n```", [], ["BETON"]);
    expect(inCode).not.toContain("data-ticket");
    const inText = renderWikiMarkdown("normale tekst BETON-91 hier", [], ["BETON"]);
    expect(inText).toContain('data-ticket="BETON-91"');
  });

  // BETON-433: agents zetten refs vaak in backticks (`TODAY-44`). Is de ref de
  // hele inhoud van de inline code, dan is hij bedoeld als verwijzing.
  it("linkificeert een ref die de hele inhoud van inline code is", () => {
    const html = renderMarkdown("gebouwd, na `TODAY-44`.", [], ["TODAY"]);
    expect(html).toContain('<code><a class="ticketlink" data-ticket="TODAY-44"');
  });

  it("laat een ref in inline code met meer tekst en in een codeblok staan", () => {
    expect(renderMarkdown("`TODAY-44 fix`", [], ["TODAY"])).not.toContain("data-ticket");
    expect(renderMarkdown("```\nTODAY-44\n```", [], ["TODAY"])).not.toContain("data-ticket");
    expect(renderMarkdown("    TODAY-44", [], ["TODAY"])).not.toContain("data-ticket");
  });

  it("breekt een wikilink niet stuk door ticketref-achtige tekst binnenin", () => {
    const html = renderWikiMarkdown("[[bestaat]]", ["bestaat"], ["BETON"]);
    expect(html).toContain('data-wiki="bestaat"');
    expect((html.match(/<a /g) || []).length).toBe(1);
  });
});

// renderMarkdown (smalle context: drawer-omschrijving, comments, triage-chat).
// Verhuisd vanuit board.test.js (BETON-132) en bijgewerkt naar markdown-it-
// output: newlines in lijsten/blockquotes, heading-offset +2, target/rel op
// links. De oude eigen parser kon geen tabellen en geen H4–H6; markdown-it
// wel — die winst wordt hieronder meegedebugd.
describe("renderMarkdown — smalle context op markdown-it (BETON-132)", () => {
  it("escapet HTML (geen XSS)", () => {
    expect(renderMarkdown("<script>alert(1)</script>")).toBe(
      "<p>&lt;script&gt;alert(1)&lt;/script&gt;</p>"
    );
  });

  it("rendert vet, cursief en inline code", () => {
    expect(renderMarkdown("**vet** en *cursief* en `code`")).toBe(
      "<p><strong>vet</strong> en <em>cursief</em> en <code>code</code></p>"
    );
  });

  it("rendert koppen met +2-offset (# → H3, ### → H5; H4–H6 clampen op H6)", () => {
    expect(renderMarkdown("# Titel")).toBe("<h3>Titel</h3>");
    expect(renderMarkdown("## Sub")).toBe("<h4>Sub</h4>");
    expect(renderMarkdown("### Diep")).toBe("<h5>Diep</h5>");
    expect(renderMarkdown("#### Nog")).toBe("<h6>Nog</h6>");
    expect(renderMarkdown("##### Diepste")).toBe("<h6>Diepste</h6>");
    expect(renderMarkdown("###### Kleinste")).toBe("<h6>Kleinste</h6>");
  });

  it("rendert ongeordende en geordende lijsten", () => {
    expect(renderMarkdown("- een\n- twee")).toBe(
      "<ul>\n<li>een</li>\n<li>twee</li>\n</ul>"
    );
    expect(renderMarkdown("1. een\n2. twee")).toBe(
      "<ol>\n<li>een</li>\n<li>twee</li>\n</ol>"
    );
  });

  it("rendert blockquotes", () => {
    expect(renderMarkdown("> citaat")).toBe(
      "<blockquote>\n<p>citaat</p>\n</blockquote>"
    );
  });

  it("rendert een horizontale lijn", () => {
    expect(renderMarkdown("---")).toBe("<hr>");
  });

  it("rendert GFM-tabellen (nieuwe mogelijkheid t.o.v. oude parser)", () => {
    const html = renderMarkdown("| A | B |\n|---|---|\n| 1 | 2 |");
    expect(html).toContain("<table>");
    expect(html).toContain("<thead>");
    expect(html).toContain("<th>A</th>");
    expect(html).toContain("<th>B</th>");
    expect(html).toContain("<tbody>");
    expect(html).toContain("<td>1</td>");
    expect(html).toContain("<td>2</td>");
  });

  it("rendert underscore-cursief en -vet op woordgrenzen", () => {
    expect(renderMarkdown("_cursief_ en __vet__")).toBe(
      "<p><em>cursief</em> en <strong>vet</strong></p>"
    );
  });

  it("laat underscores midden in een woord (snake_case) met rust", () => {
    expect(renderMarkdown("een some_var_naam hier")).toBe(
      "<p>een some_var_naam hier</p>"
    );
  });
});

describe("renderMarkdown — veilige URLs (BETON-5)", () => {
  it("staat alleen veilige links toe (met target/rel)", () => {
    const html = renderMarkdown("[ok](https://x.nl)");
    expect(html).toContain('href="https://x.nl"');
    expect(html).toContain('target="_blank"');
    expect(html).toContain('rel="noopener noreferrer"');
  });

  it("weigert javascript:-links (letterlijk laten staan)", () => {
    expect(renderMarkdown("[nee](javascript:alert(1))")).toBe(
      "<p>[nee](javascript:alert(1))</p>"
    );
  });

  it("rendert afbeeldingen met veilige URL (attachment-serve of http)", () => {
    expect(renderMarkdown("![kat](/api/v1/attachments/abc)")).toBe(
      '<p><img src="/api/v1/attachments/abc" alt="kat"></p>'
    );
    expect(renderMarkdown("![x](https://x.nl/p.png)")).toContain(
      '<img src="https://x.nl/p.png"'
    );
  });

  it("weigert onveilige image-URLs (letterlijk laten staan)", () => {
    expect(renderMarkdown("![x](javascript:alert(1))")).toBe(
      "<p>![x](javascript:alert(1))</p>"
    );
  });
});

describe("renderMarkdown — @handle mentions (BETON-60)", () => {
  it("rendert @handle van een bekende user als mention-chip", () => {
    const html = renderMarkdown("hoi @person", ["person", "claude"]);
    expect(html).toContain(
      '<span class="mention" data-mention="person">@person</span>'
    );
  });

  it("laat een onbekende @handle als platte tekst staan", () => {
    expect(renderMarkdown("hoi @niemand", ["person"])).toBe("<p>hoi @niemand</p>");
  });

  it("zonder known-handles worden mentions niet omgezet", () => {
    expect(renderMarkdown("hoi @person")).toBe("<p>hoi @person</p>");
  });

  it("matcht bekende handles case-insensitief", () => {
    expect(renderMarkdown("@Person", ["person"])).toContain('class="mention"');
  });

  it("negeert e-mailachtige @ na een woordkarakter", () => {
    expect(renderMarkdown("mail person@claude nu", ["claude"])).toBe(
      "<p>mail person@claude nu</p>"
    );
  });

  it("houdt escaping intact rond een mention (geen XSS)", () => {
    const html = renderMarkdown("<b>@person</b>", ["person"]);
    expect(html).toContain("&lt;b&gt;");
    expect(html).toContain(
      '<span class="mention" data-mention="person">@person</span>'
    );
    expect(html).not.toContain("<b>");
  });

  it("accepteert known-handles als Set", () => {
    expect(renderMarkdown("@claude", new Set(["claude"]))).toContain(
      'class="mention"'
    );
  });
});

describe("renderMarkdown — ticketref-linkificatie (BETON-107)", () => {
  it("linkificeert ticketrefs van bekende project-keys", () => {
    const html = renderMarkdown("zie BETON-91", [], ["BETON"]);
    expect(html).toContain('data-ticket="BETON-91"');
    expect(html).toContain('class="ticketlink"');
  });

  it("linkificeert geen ticketrefs zonder knownProjectKeys (backward-compat)", () => {
    const html = renderMarkdown("zie BETON-91");
    expect(html).not.toContain("data-ticket");
    expect(html).toBe("<p>zie BETON-91</p>");
  });

  it("linkificeert geen ticketrefs van onbekende project-keys", () => {
    const html = renderMarkdown("zie COVID-19", [], ["BETON"]);
    expect(html).not.toContain("data-ticket");
  });

  it("linkificeert geen ticketrefs binnen een codeblok", () => {
    const html = renderMarkdown("```\nBETON-91\n```", [], ["BETON"]);
    expect(html).not.toContain("data-ticket");
  });

  it("breekt geen tag-attributen door ticket-linkificatie", () => {
    const html = renderMarkdown("[BETON-91](https://x.nl/BETON-91)", [], ["BETON"]);
    expect(html).toContain('href="https://x.nl/BETON-91"');
    // De linktekst zelf mag wel gelinkt worden, maar de href mag niet stuk.
    const hrefCount = (html.match(/href="https:\/\/x\.nl\/BETON-91"/g) || []).length;
    expect(hrefCount).toBe(1);
  });

  it("combineert mentions en ticketrefs zonder conflict", () => {
    const html = renderMarkdown("@person zie BETON-1", ["person"], ["BETON"]);
    expect(html).toContain('class="mention" data-mention="person"');
    expect(html).toContain('data-ticket="BETON-1"');
  });
});

describe("renderMarkdown — kale URL's worden klikbaar (BETON-406)", () => {
  it("linkificeert een kale http(s)-URL met target/rel", () => {
    const html = renderMarkdown("zie https://example.com/pad voor meer");
    expect(html).toContain('href="https://example.com/pad"');
    expect(html).toContain('target="_blank"');
    expect(html).toContain('rel="noopener noreferrer"');
  });

  it("laat een kale javascript:-tekst als platte tekst staan (geen link)", () => {
    const html = renderMarkdown("kijk naar javascript:alert(1) hier");
    expect(html).not.toContain("<a ");
    expect(html).not.toContain("href=");
    expect(html).toContain("javascript:alert(1)");
  });

  it("laat een kale data:-tekst als platte tekst staan (geen link)", () => {
    const html = renderMarkdown("data:text/html,<script>evil</script> blijft tekst");
    expect(html).not.toContain("<a ");
    // html:false escapet de <script> hier al; de kern van de test is dat er
    // geen href/data:-link ontstaat.
    expect(html).not.toContain('href="data:');
  });

  it("linkificeert geen kaal domein zonder http(s)-schema (fuzzy-matching valt af op de whitelist)", () => {
    const html = renderMarkdown("ga naar www.example.com nu");
    expect(html).not.toContain("<a ");
    expect(html).toContain("www.example.com");
  });

  it("linkificeert geen kaal e-mailadres (mailto: staat niet op de whitelist)", () => {
    const html = renderMarkdown("mail naar iemand@example.com nu");
    expect(html).not.toContain("<a ");
    expect(html).not.toContain("mailto:");
    expect(html).toContain("iemand@example.com");
  });

  it("linkificeert een URL binnen een codespan NIET (blijft tekst)", () => {
    const html = renderMarkdown("gebruik `https://example.com/pad` in code");
    expect(html).toContain("<code>https://example.com/pad</code>");
    expect(html).not.toContain('href="https://example.com/pad"');
  });

  it("linkificeert een URL binnen een codeblok NIET (blijft tekst)", () => {
    const html = renderMarkdown("```\nhttps://example.com/pad\n```");
    expect(html).not.toContain('href="https://example.com/pad"');
    expect(html).toContain("https://example.com/pad");
  });

  it("linkificeert een bestaande markdown-link ([tekst](url)) niet dubbel", () => {
    const html = renderMarkdown("[hier](https://example.com/pad)");
    const hrefCount = (html.match(/href="https:\/\/example\.com\/pad"/g) || []).length;
    expect(hrefCount).toBe(1);
    expect(html).toContain(">hier<");
  });

  it("een gelinkifyde URL met een ticketref-achtig patroon blijft één link (BETON-406/107-interactie)", () => {
    const html = renderMarkdown("zie https://example.com/BETON-123 voor context", [], ["BETON"]);
    // Precies één <a> rond de hele URL, geen tweede <a> genest in de tekst.
    const anchorCount = (html.match(/<a\b/g) || []).length;
    expect(anchorCount).toBe(1);
    expect(html).toContain('href="https://example.com/BETON-123"');
    expect(html).not.toContain("data-ticket");
  });

  it("een handmatige markdown-link met ticketref als linktekst blijft (bestaand gedrag, BETON-107)", () => {
    // Contrast met de vorige test: een expliciete [BETON-91](url) mag de
    // linktekst zelf wél laten linkificeren (BETON-107) — alleen de
    // ZICHTBARE TEKST van een autolinked URL (die de URL zelf is) wordt
    // ontzien.
    const html = renderMarkdown("[BETON-91](https://x.nl/BETON-91)", [], ["BETON"]);
    expect(html).toContain('href="https://x.nl/BETON-91"');
    expect(html).toContain('data-ticket="BETON-91"');
  });
});

// <details>/<summary> op een whitelist (BETON-458). Alleen de kale tags komen
// door; alle andere HTML en alle attributen blijven ge-escaped.
describe("renderMarkdown — <details>/<summary> whitelist (BETON-458)", () => {
  it("laat details/summary door met markdown in de body", () => {
    const html = renderMarkdown("<details>\n<summary>Meer</summary>\n\n**vet** erin\n\n</details>");
    expect(html).toContain("<details>");
    expect(html).toContain("<summary>Meer</summary>");
    expect(html).toContain("<strong>vet</strong>");
    expect(html).toContain("</details>");
  });

  it("strips attributen: onclick op details komt niet door", () => {
    const html = renderMarkdown('<details onclick="alert(1)">\n<summary>x</summary>\n\nbody\n\n</details>');
    expect(html).not.toMatch(/<details[^>]*onclick/i);
    expect(html).toContain("&lt;details onclick=");
  });

  it("script en andere tags blijven ge-escaped, ook naast details", () => {
    const html = renderMarkdown("<details>\n<summary>x</summary>\n<script>alert(1)</script>\n\n</details>");
    expect(html).not.toContain("<script");
    expect(html).toContain("&lt;script&gt;");
    expect(renderMarkdown("tekst <b onclick=x>vet</b> en <summary onclick=x>")).not.toMatch(/<(b|summary)[ >]/);
  });

  it("inline summary/details tags in lopende tekst: alleen kale tags", () => {
    const html = renderMarkdown("a <summary>b</summary>");
    expect(html).toContain("<summary>b</summary>");
  });

  it("in code blijft het tekst", () => {
    expect(renderMarkdown("`<details>`")).toBe("<p><code>&lt;details&gt;</code></p>");
    expect(renderMarkdown("```\n<details>\n```")).toContain("&lt;details&gt;");
  });
});

// Regressie: al het andere HTML rendert byte-voor-byte als vóór html:true (BETON-458).
describe("renderMarkdown — niet-toegestane HTML blijft gelijk aan html:false (BETON-458)", () => {
  it("<div> onderbreekt een alinea niet", () => {
    expect(renderMarkdown("tekst\n<div>x</div>")).toBe("<p>tekst\n&lt;div&gt;x&lt;/div&gt;</p>");
  });
  it("<script>/<style>/<!-- --> slokken geen lege regels en blijven alinea's", () => {
    expect(renderMarkdown("<script>\nalert(1)\n\n**b**")).toBe(
      "<p>&lt;script&gt;\nalert(1)</p>\n<p><strong>b</strong></p>"
    );
    expect(renderMarkdown("<!-- c -->\n\nx")).toBe("<p>&lt;!-- c --&gt;</p>\n<p>x</p>");
  });
  it("lijstitems en blockquotes blijven strak", () => {
    expect(renderMarkdown("- a\n- <div>x</div>")).toBe("<ul>\n<li>a</li>\n<li>&lt;div&gt;x&lt;/div&gt;</li>\n</ul>");
    expect(renderMarkdown("> <div>q</div>")).toBe("<blockquote>\n<p>&lt;div&gt;q&lt;/div&gt;</p>\n</blockquote>");
  });
  it("hoofdletters en entiteiten in een details-blok", () => {
    expect(renderMarkdown("<DETAILS>x</DETAILS>")).toContain("<details>x</details>");
    expect(renderMarkdown("<details>&nbsp;<img src=x onerror=1>")).toBe(
      "<details>&nbsp;&lt;img src=x onerror=1&gt;"
    );
  });
});


it("escapet onbetrouwbare wiki-scope-attributen (BETON-502)", () => {
  const scope = '\" oncut=alert(1) x=\"';
  const html = renderWikiMarkdown("[[demo]]", new Set([`${scope} demo`]), [], scope);
  expect(html).toContain('data-wiki-scope="&quot; oncut=alert(1) x=&quot;"');
  expect(html).not.toContain('data-wiki-scope="" oncut=');
});


it("bewerkt mentions en wikilinks niet binnen bestaande attributen", () => {
  expect(renderMarkdown('[tekst](https://example.com "@alice")', ["alice"]))
    .toContain('title="@alice"');
  expect(renderWikiMarkdown('[tekst](https://example.com "[[demo]]")', new Set(["global demo"])))
    .toContain('title="[[demo]]"');
});
