<script lang="ts">
	let { connected }: { connected: boolean } = $props();
</script>

<span role="status" class:connected>
	{connected ? 'Connected' : 'Disconnected'}
</span>
