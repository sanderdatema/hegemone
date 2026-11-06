<script>
  import { avatarColor, initials } from "./lib/avatar.js";

  let { handle, size = 24, title = null, avatarUrl = null } = $props();
</script>

{#if avatarUrl}
  <img
    class="avatar avatar-img"
    style:--sz="{size}px"
    src={avatarUrl}
    alt=""
    title={title ?? `@${handle}`}
  />
{:else}
  <span
    class="avatar"
    style:--sz="{size}px"
    style:--avatar-bg={avatarColor(handle)}
    title={title ?? `@${handle}`}
    aria-hidden="true"
  >
    {initials(handle)}
  </span>
{/if}

<style>
  .avatar {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: var(--sz);
    height: var(--sz);
    border-radius: var(--radius-full);
    background: var(--avatar-bg);
    color: var(--on-solid);
    font-size: calc(var(--sz) * 0.4);
    font-weight: 600;
    line-height: 1;
    letter-spacing: 0.02em;
    flex: 0 0 auto;
    user-select: none;
  }
  .avatar-img {
    object-fit: cover;
    background: var(--surface-3);
  }
</style>
