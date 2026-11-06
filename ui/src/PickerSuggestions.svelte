<script>
  let { mentions = [], tickets = [], mentionActive = 0, ticketActive = 0, onmention, onticket, id = undefined } = $props();
</script>
{#if mentions.length || tickets.length}
  <ul {id} class="mention-list" role="listbox" aria-label="Invoersuggesties">
    {#each mentions.length ? mentions : tickets as row, index (row.handle ?? row.ref)}
      <li role="option" aria-selected={index === (mentions.length ? mentionActive : ticketActive)} class:active={index === (mentions.length ? mentionActive : ticketActive)}>
        <button type="button" onmousedown={(e) => e.preventDefault()} onclick={() => mentions.length ? onmention(row.handle) : onticket(row.ref)}>
          <span class="rel-suggest-ref">{mentions.length ? `@${row.handle}` : row.ref}</span>
          <span class="muted">{mentions.length ? row.display_name : row.title}</span>
        </button>
      </li>
    {/each}
  </ul>
{/if}
<style>
  button { width: 100%; text-align: left; justify-content: flex-start; border: 0; background: transparent; padding: 0; color: inherit; }
</style>
