import { afterEach, describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from '../mocks/server';
import { MakerworldChinaPublicPage } from '../../pages/MakerworldChinaPublicPage';

afterEach(() => server.resetHandlers());

describe('MakerworldChinaPublicPage', () => {
  it('resolves a China model link and displays its downloadable plates', async () => {
    server.use(
      http.post('*/makerworld/public/china/resolve', async ({ request }) => {
        const body = await request.json() as { url: string };
        expect(body.url).toBe('https://makerworld.cn/zh/models/1400373');
        return HttpResponse.json({
          model_id: 1400373,
          account_id: null,
          region: 'china',
          profile_id: 298919107,
          design: { title: 'Seed Starter', designCreator: { name: 'Maker' } },
          instances: [
            { id: 1, profileId: 298919107, title: '9 cells' },
            { id: 2, profileId: 298919564, title: '12 cells' },
          ],
          already_imported_library_ids: [],
        });
      }),
    );
    const queryClient = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
    render(
      <QueryClientProvider client={queryClient}>
        <MakerworldChinaPublicPage />
      </QueryClientProvider>,
    );

    await userEvent.type(
      screen.getByRole('textbox', { name: 'MakerWorld China URL' }),
      'https://makerworld.cn/zh/models/1400373',
    );
    await userEvent.click(screen.getByRole('button', { name: /Preview/i }));

    expect(await screen.findByRole('heading', { name: 'Seed Starter' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /9 cells/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /12 cells/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Download 3MF/i })).toBeEnabled();
  });
});
