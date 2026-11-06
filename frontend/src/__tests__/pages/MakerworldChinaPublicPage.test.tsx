import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from '../mocks/server';
import { MakerworldChinaPublicPage } from '../../pages/MakerworldChinaPublicPage';
import { api } from '../../api/client';

const publicStats = {
  total_visits: 1234,
  total_downloads: 180,
  downloads_today: 5,
  daily_limit: 20,
  remaining_downloads: 15,
  resets_at: '2026-11-06T00:00:00+07:00',
};

beforeEach(() => {
  server.use(
    http.get('*/makerworld/public/china/stats', () => HttpResponse.json(publicStats)),
    http.post('*/makerworld/public/china/visit', () => HttpResponse.json(publicStats)),
  );
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
  server.resetHandlers();
  localStorage.removeItem('makerworld-cn-show-preview-images');
});

describe('MakerworldChinaPublicPage', () => {
  it('counts one visit and shows the global daily quota', async () => {
    const recordVisit = vi.spyOn(api, 'recordPublicChinaMakerworldVisit').mockResolvedValue(publicStats);
    const { rerender } = render(
      <QueryClientProvider client={new QueryClient()}><MakerworldChinaPublicPage /></QueryClientProvider>,
    );
    const stats = screen.getByRole('region', { name: 'Thống kê truy cập và tải xuống' });
    expect(await within(stats).findByText('1.234')).toBeInTheDocument();
    expect(within(stats).getByText('180')).toBeInTheDocument();
    expect(within(stats).getByText('5')).toBeInTheDocument();
    expect(within(stats).getByText('15')).toBeInTheDocument();
    expect(within(stats).getByText(/Toàn trang được tải tối đa 20 file/)).toBeInTheDocument();
    await userEvent.type(screen.getByRole('textbox'), 'test');
    expect(recordVisit).toHaveBeenCalledTimes(1);
  });

  it('refreshes statistics after the last available file and disables further downloads', async () => {
    let downloadsToday = 19;
    const currentStats = () => ({ ...publicStats, downloads_today: downloadsToday, remaining_downloads: 20 - downloadsToday });
    server.use(
      http.get('*/makerworld/public/china/stats', () => HttpResponse.json(currentStats())),
      http.post('*/makerworld/public/china/visit', () => HttpResponse.json(currentStats())),
      http.post('*/makerworld/public/china/resolve', () => HttpResponse.json({
        model_id: 123, profile_id: 456, design: { title: 'Last file' },
        instances: [{ profileId: 456, title: 'Plate' }],
      })),
    );
    const downloadFile = vi.spyOn(api, 'downloadPublicChinaMakerworldInstance').mockImplementation(async () => { downloadsToday += 1; });
    render(<QueryClientProvider client={new QueryClient()}><MakerworldChinaPublicPage /></QueryClientProvider>);
    await userEvent.type(screen.getByRole('textbox'), 'https://makerworld.cn/zh/models/123');
    await userEvent.click(screen.getByRole('button', { name: 'Xem mẫu' }));
    await screen.findByRole('heading', { name: 'Last file' });
    await userEvent.click(screen.getByRole('button', { name: 'Tải 3MF' }));
    expect(await screen.findByRole('button', { name: 'Đã hết lượt tải hôm nay' })).toBeDisabled();
    expect(screen.getByText(/Trang đã hết lượt tải hôm nay/)).toBeInTheDocument();
    expect(downloadFile).toHaveBeenCalledTimes(1);
    const stats = screen.getByRole('region', { name: 'Thống kê truy cập và tải xuống' });
    expect(within(stats).getByText('20')).toBeInTheDocument();
    expect(within(stats).getByText('0')).toBeInTheDocument();
  });

  it('downloads only the selected file and waits 20 seconds before allowing another download', async () => {
    server.use(
      http.post('*/makerworld/public/china/resolve', () => HttpResponse.json({
        model_id: 123,
        profile_id: 456,
        design: { title: 'Test model' },
        instances: [
          { profileId: 456, title: 'First file' },
          { profileId: 789, title: 'Second file' },
        ],
      })),
    );
    let completeDownload!: () => void;
    const downloadFile = vi.spyOn(api, 'downloadPublicChinaMakerworldInstance')
      .mockImplementationOnce(() => new Promise<void>((resolveDownload) => { completeDownload = resolveDownload; }))
      .mockResolvedValue(undefined);
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { mutations: { retry: false } } })}>
        <MakerworldChinaPublicPage />
      </QueryClientProvider>,
    );
    await userEvent.type(screen.getByRole('textbox'), 'https://makerworld.cn/zh/models/123');
    await userEvent.click(screen.getByRole('button', { name: 'Xem mẫu' }));
    await screen.findByRole('heading', { name: 'Test model' });
    expect(screen.queryByRole('button', { name: /Tải tất cả|ZIP/i })).not.toBeInTheDocument();

    vi.useFakeTimers();
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Tải 3MF' })); });
    await act(async () => { vi.advanceTimersByTime(1); });
    expect(downloadFile).toHaveBeenCalledExactlyOnceWith(123, 456);
    expect(screen.getByRole('button', { name: 'Đang tải…' })).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: /Second file/ }));
    await act(async () => { completeDownload(); });
    await act(async () => { vi.advanceTimersByTime(1); });
    expect(screen.getByRole('button', { name: 'Tải tiếp sau 20s' })).toBeDisabled();
    await act(async () => { vi.advanceTimersByTime(19_000); });
    const waitingButton = screen.getByRole('button', { name: 'Tải tiếp sau 1s' });
    fireEvent.click(waitingButton);
    expect(downloadFile).toHaveBeenCalledTimes(1);
    await act(async () => { vi.advanceTimersByTime(1000); });
    expect(screen.getByRole('button', { name: 'Tải 3MF' })).toBeEnabled();
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Tải 3MF' })); });
    expect(downloadFile).toHaveBeenLastCalledWith(123, 789);
    expect(downloadFile).toHaveBeenCalledTimes(2);
  });

  it('skips preview media when disabled before resolving a model', async () => {
    server.use(
      http.post('*/makerworld/public/china/resolve', () => HttpResponse.json({
        model_id: 123,
        account_id: null,
        region: 'china',
        profile_id: 456,
        design: {
          title: 'Slow preview model',
          coverUrl: 'https://makerworld.bblmw.com/cover.jpg',
          summary: '<p>Model notes</p><video poster="https://makerworld.bblmw.com/video.jpg"><source src="https://makerworld.bblmw.com/demo.mp4"></video><img src="https://makerworld.bblmw.com/description.jpg">',
          designExtension: {},
        },
        instances: [{ id: 1, profileId: 456, title: 'Plate', cover: 'https://makerworld.bblmw.com/plate.jpg' }],
        already_imported_library_ids: [],
      })),
    );
    const queryClient = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
    const { container } = render(
      <QueryClientProvider client={queryClient}>
        <MakerworldChinaPublicPage />
      </QueryClientProvider>,
    );

    const user = userEvent.setup();
    const previewToggle = screen.getByRole('checkbox', { name: /Hiện ảnh xem trước/i });
    expect(previewToggle).toBeChecked();
    await user.click(previewToggle);
    await user.type(screen.getByRole('textbox', { name: 'Liên kết MakerWorld China' }), 'https://makerworld.cn/zh/models/123');
    await user.click(screen.getByRole('button', { name: /Xem mẫu/i }));

    expect(await screen.findByRole('heading', { name: 'Slow preview model' })).toBeInTheDocument();
    expect(container.querySelector('img')).not.toBeInTheDocument();
    await user.click(screen.getByRole('tab', { name: 'Mô tả, giới thiệu' }));
    const description = screen.getByRole('tabpanel');
    expect(within(description).getByText('Model notes')).toBeInTheDocument();
    expect(description.querySelector('img, video, audio, iframe, source')).not.toBeInTheDocument();
    await user.click(screen.getByRole('tab', { name: 'Các bàn in' }));
    expect(screen.getByRole('button', { name: 'Tải 3MF' })).toBeEnabled();
  });

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
            summary: '<p>Printable seed tray</p><img src="https://makerworld.bblmw.com/description-large.jpg" width="2400" height="1800"><script>window.pwned = true</script>',
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
    expect(screen.queryByText('Printable seed tray')).not.toBeInTheDocument();
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
    expect(screen.queryByRole('button', { name: /Tải tất cả|\.ZIP/i })).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole('tab', { name: 'Tài liệu và hướng dẫn' }));
    expect(screen.getByText('MiniVF2_BASIC.pdf')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Xem MiniVF2_BASIC.pdf' })).toHaveAttribute('href', 'https://makerworld.bblmw.cn/guide.pdf');

    await userEvent.click(screen.getByRole('tab', { name: 'Mô tả, giới thiệu' }));
    const descriptionPanel = screen.getByRole('tabpanel');
    expect(within(descriptionPanel).getByText('Printable seed tray')).toBeInTheDocument();
    expect(within(descriptionPanel).getByText('Printable seed tray').parentElement).not.toHaveClass('line-clamp-3');
    expect(descriptionPanel.querySelector('.makerworld-description img')).toHaveAttribute('src', expect.stringContaining('/api/v1/makerworld/thumbnail?url='));

    await userEvent.click(screen.getByRole('tab', { name: 'Vật tư yêu cầu' }));
    expect(screen.getByText('M3x8 screws')).toBeInTheDocument();
    expect(screen.getByText('PLA Basic')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Mở M3x8 screws' })).toHaveAttribute('href', 'https://store.bambulab.com/screws');
    expect(container.querySelector('img[src*="screw.png"]')).toBeInTheDocument();

    const previewToggle = screen.getByRole('checkbox', { name: /Hiện ảnh xem trước/i });
    expect(previewToggle).toBeChecked();
    await userEvent.click(previewToggle);
    expect(previewToggle).not.toBeChecked();
    expect(localStorage.setItem).toHaveBeenCalledWith('makerworld-cn-show-preview-images', 'false');
    expect(container.querySelectorAll('img[src*="/api/v1/makerworld/thumbnail"]')).toHaveLength(0);

    await userEvent.click(screen.getByRole('tab', { name: 'Mô tả, giới thiệu' }));
    const descriptionWithoutMedia = screen.getByRole('tabpanel');
    expect(within(descriptionWithoutMedia).getByText('Printable seed tray')).toBeInTheDocument();
    expect(descriptionWithoutMedia.querySelector('img, video, iframe')).not.toBeInTheDocument();

    await userEvent.click(previewToggle);
    expect(previewToggle).toBeChecked();
    expect(localStorage.setItem).toHaveBeenCalledWith('makerworld-cn-show-preview-images', 'true');
    expect(descriptionWithoutMedia.querySelector('.makerworld-description img')).toBeInTheDocument();
  });
});
