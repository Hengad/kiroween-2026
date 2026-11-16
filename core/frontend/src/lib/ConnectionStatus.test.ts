import { render, screen } from '@testing-library/svelte';
import { describe, expect, it } from 'vitest';

import ConnectionStatus from './ConnectionStatus.svelte';

describe('ConnectionStatus', () => {
	it('announces when the live connection is established', () => {
		render(ConnectionStatus, { connected: true });

		expect(screen.getByRole('status')).toHaveTextContent('Connected');
	});

	it('announces when the live connection is lost', () => {
		render(ConnectionStatus, { connected: false });

		expect(screen.getByRole('status')).toHaveTextContent('Disconnected');
	});
});
