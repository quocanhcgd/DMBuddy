import { afterEach, describe, expect, it } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from '../mocks/server';
import { MakerworldChinaPublicPage } from '../../pages/MakerworldChinaPublicPage';

afterEach(() => server.resetHandlers());

describe('MakerworldChinaPublicPage', () => {
  it('resolves a China model link and displays its downloadable plates', async () => {
    server.use(
      http.get('/api/v1/updates/version', () => HttpResponse.json({
        version: '0.2.5.4',
        display_version: '0.2.5.4 (abc1234)',
        source_ref_short: 'abc1234',
      })),
      http.post('*/makerworld/public/china/resolve', async ({ request }) => {
        const body = await request.json() as { url: string };
        expect(body.url).toBe('https://makerworld.cn/zh/models/1400373');
        return HttpResponse.json({
          model_id: 1400373,
          account_id: null,
          region: 'china',
          profile_id: 298919107,
          design: {
            title: 'Seed Starter',
            designCreator: { name: 'Maker' },
            summary: '<p>Printable seed tray</p><script>window.pwned = true</script>',
            downloadCount: 1234,
            license: 'CC BY-NC-SA',
            designExtension: {
              design_guide: [{ name: 'MiniVF2_BASIC.pdf', url: 'https://makerworld.bblmw.cn/guide.pdf' }],
              boms: [{ sku: 'AA037', parentTitle: 'M3x8 screws', displayTitle: 'B-AA037', quantity: 1, url: 'https://store.bambulab.com/screws', image: 'https://store.bblcdn.com/screw.png' }],
              boms_of_filaments: [{ sku: 'PLA-BLACK', parentTitle: 'PLA Basic', title: 'Black', quantity: 1 }],
            },
          },
          instances: [
            {
              id: 1,
              profileId: 298919107,
              title: '9 cells',
              materialCnt: 2,
              needAms: true,
              downloadCount: 87,
              cover: 'https://makerworld.bblmw.com/profile-cover.png',
              plateCount: 5,
              printTimeSeconds: 37800,
              ratingScoreTotal: 5,
              ratingCount: 1,
              compatibility: { devProductName: 'A1 mini' },
              otherCompatibility: [{ devProductName: 'A1' }],
              thumbnailUrl: 'https://makerworld.bblmw.com/preview.png',
            },
            { id: 2, profileId: 298919564, title: '12 cells' },
          ],
          already_imported_library_ids: [],
        });
      }),
    );
    const queryClient = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
    const { container } = render(
      <QueryClientProvider client={queryClient}>
        <MakerworldChinaPublicPage />
      </QueryClientProvider>,
    );

    await userEvent.type(
      screen.getByRole('textbox', { name: 'Liên kết MakerWorld China' }),
      'https://makerworld.cn/zh/models/1400373',
    );
    const footer = screen.getByRole('contentinfo');
    expect(footer).toHaveTextContent('© 2026. Bản quyền thuộc về DM2026.');
    expect(await screen.findByRole('contentinfo')).toHaveTextContent('Phiên bản v0.2.5.4 (abc1234)');
    expect(screen.getByRole('link', { name: 'Ủng hộ' })).toHaveAttribute('href', '/support');
    await userEvent.click(screen.getByRole('button', { name: /Xem mẫu/i }));

    expect(await screen.findByRole('heading', { name: 'Seed Starter' })).toBeInTheDocument();
    expect(screen.getByText('Printable seed tray')).toBeInTheDocument();
    expect(screen.getByText('Printable seed tray').parentElement).toHaveClass('line-clamp-3');
    expect(screen.queryByText(/window.pwned/)).not.toBeInTheDocument();
    expect(screen.getByText('1,234 lượt tải')).toBeInTheDocument();
    expect(screen.getByText('Giấy phép: CC BY-NC-SA')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /9 cells/i })).toBeInTheDocument();
    expect(container.querySelector('img[src*="profile-cover.png"]')).toBeInTheDocument();
    expect(screen.getByText('Tối ưu cho A1 mini')).toBeInTheDocument();
    expect(screen.getByText('2 loại vật liệu')).toBeInTheDocument();
    expect(screen.getByText('Cần AMS')).toBeInTheDocument();
    expect(screen.getByText('10.5 giờ')).toBeInTheDocument();
    expect(screen.getByText('5 bàn in')).toBeInTheDocument();
    expect(screen.getByText('5.0 (1)')).toBeInTheDocument();
    expect(screen.getByText('Tương thích thêm: A1')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /12 cells/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Tải 3MF/i })).toBeEnabled();
    expect(screen.getByRole('button', { name: /Tải tất cả/i })).toBeEnabled();

    await userEvent.click(screen.getByRole('tab', { name: 'Tài liệu và hướng dẫn' }));
    expect(screen.getByText('MiniVF2_BASIC.pdf')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Xem MiniVF2_BASIC.pdf' })).toHaveAttribute('href', 'https://makerworld.bblmw.cn/guide.pdf');

    await userEvent.click(screen.getByRole('tab', { name: 'Mô tả, giới thiệu' }));
    const descriptionPanel = screen.getByRole('tabpanel');
    expect(within(descriptionPanel).getByText('Printable seed tray')).toBeInTheDocument();
    expect(within(descriptionPanel).getByText('Printable seed tray').parentElement).not.toHaveClass('line-clamp-3');

    await userEvent.click(screen.getByRole('tab', { name: 'Vật tư yêu cầu' }));
    expect(screen.getByText('M3x8 screws')).toBeInTheDocument();
    expect(screen.getByText('PLA Basic')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Mở M3x8 screws' })).toHaveAttribute('href', 'https://store.bambulab.com/screws');
    expect(container.querySelector('img[src*="screw.png"]')).toBeInTheDocument();
  });
});
