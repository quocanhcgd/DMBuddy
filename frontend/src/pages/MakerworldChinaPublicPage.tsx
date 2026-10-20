import { useState } from 'react';
import DOMPurify from 'dompurify';
import JSZip from 'jszip';
import { AlertCircle, Clock3, Download, ExternalLink, Eye, FileText, Heart, LoaderCircle, PanelsTopLeft, Search, Star } from 'lucide-react';
import { useMutation, useQuery } from '@tanstack/react-query';
import { api, type MakerworldResolvedModel } from '../api/client';
import { Button } from '../components/Button';

function textField(value: unknown): string {
  return typeof value === 'string' ? value : '';
}

function imageUrl(value: string): string {
  if (!/^https?:\/\/(?:(?:makerworld|public-cdn)\.bblmw\.(?:com|cn)|store\.bblcdn\.com)\//i.test(value)) return '';
  return `/api/v1/makerworld/thumbnail?url=${encodeURIComponent(value)}`;
}

function safeHtml(value: string): string {
  const proxied = value.replace(
    /https?:\/\/(?:makerworld|public-cdn)\.bblmw\.(?:com|cn)\/[^\s"']+/gi,
    (url) => imageUrl(url),
  );
  return DOMPurify.sanitize(proxied);
}

function numberField(value: unknown): number | null {
  return typeof value === 'number' ? value : null;
}

function formatPrintTime(seconds: number): string {
  const hours = seconds / 3600;
  return `${Number.isInteger(hours) ? hours : hours.toFixed(1)} giờ`;
}

type MakerworldTab = 'plates' | 'guides' | 'description' | 'materials';

function objectField(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function arrayField(value: unknown): Array<Record<string, unknown>> {
  return Array.isArray(value) ? value.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === 'object') : [];
}

export function MakerworldChinaPublicPage() {
  const [url, setUrl] = useState('');
  const [resolved, setResolved] = useState<MakerworldResolvedModel | null>(null);
  const [selectedProfile, setSelectedProfile] = useState<number | null>(null);
  const [activeTab, setActiveTab] = useState<MakerworldTab>('plates');
  const [batchProgress, setBatchProgress] = useState<{ current: number; total: number } | null>(null);
  const versionQuery = useQuery({
    queryKey: ['version'],
    queryFn: api.getVersion,
    staleTime: Infinity,
  });
  const resolve = useMutation({
    mutationFn: api.resolvePublicChinaMakerworldUrl,
    onSuccess: (data) => {
      setResolved(data);
      setSelectedProfile(data.profile_id ?? null);
    },
  });
  const download = useMutation({
    mutationFn: ({ modelId, profileId }: { modelId: number; profileId: number }) =>
      api.downloadPublicChinaMakerworldInstance(modelId, profileId),
  });
  const downloadAll = useMutation({
    mutationFn: async ({ modelId, plates }: { modelId: number; plates: Array<Record<string, unknown>> }) => {
      const zip = new JSZip();
      for (const [index, plate] of plates.entries()) {
        const profileId = numberField(plate.profileId);
        if (profileId === null) continue;
        setBatchProgress({ current: index + 1, total: plates.length });
        const { blob } = await api.fetchPublicChinaMakerworldInstance(modelId, profileId);
        const plateTitle = textField(plate.title) || `plate-${index + 1}`;
        const safeTitle = plateTitle.replace(/[\\/:*?"<>|]/g, '-').trim();
        zip.file(`${String(index + 1).padStart(2, '0')}-${safeTitle}-${profileId}.3mf`, blob);
        setBatchProgress({ current: index + 1, total: plates.length });
      }
      return zip.generateAsync({ type: 'blob' });
    },
    onSettled: () => setBatchProgress(null),
    onSuccess: (blob) => {
      const objectUrl = window.URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = objectUrl;
      anchor.download = `makerworld-${resolved?.model_id ?? 'china'}-plates.zip`;
      document.body.appendChild(anchor);
      anchor.click();
      document.body.removeChild(anchor);
      window.URL.revokeObjectURL(objectUrl);
    },
  });

  const design = resolved?.design;
  const title = textField(design?.title) || 'Mẫu MakerWorld';
  const cover = imageUrl(textField(design?.coverUrl));
  const summary = textField(design?.summary);
  const downloads = numberField(design?.downloadCount);
  const license = textField(design?.license);
  const creator = design?.designCreator && typeof design.designCreator === 'object'
    ? textField((design.designCreator as Record<string, unknown>).name)
    : '';
  const instances = resolved?.instances ?? [];
  const designExtension = objectField(design?.designExtension);
  const guides = arrayField(designExtension.design_guide);
  const materials = [
    ...arrayField(designExtension.boms),
    ...arrayField(designExtension.boms_of_filaments),
    ...arrayField(designExtension.boms_of_materials),
    ...arrayField(designExtension.boms_of_other_parts),
  ];
  const selected = instances.find((item) => item.profileId === selectedProfile);
  const error = resolve.error ?? download.error ?? downloadAll.error;

  return (
    <main className="min-h-screen bg-bambu-dark text-bambu-gray-light">
      <header className="border-b border-bambu-gray-dark/30">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-5 py-4">
          <a href="/" className="font-semibold tracking-wide text-white">DMbuddy</a>
          <div className="flex items-center gap-4">
            <span className="hidden items-center gap-2 text-sm text-bambu-gray sm:inline-flex">
              <span className="h-2 w-2 rounded-full bg-status-ok" /> MakerWorld China
            </span>
            <a
              href="/support"
              className="inline-flex min-h-10 items-center gap-2 rounded-md border border-bambu-gray-dark/50 px-3 text-sm font-medium text-white transition-colors hover:border-rose-400/60 hover:text-rose-300"
            >
              <Heart className="h-4 w-4" />
              Ủng hộ
            </a>
          </div>
        </div>
      </header>

      <div className="mx-auto max-w-6xl px-5 pb-16 pt-8">
        <div className="mb-7 max-w-3xl">
          <h1 className="text-2xl font-semibold text-white">MakerWorld China</h1>
          <p className="mt-1 text-sm text-bambu-gray">Dán liên kết mẫu MakerWorld China để xem thông tin và tải file 3MF.</p>
        </div>

        <form
          className="flex max-w-4xl flex-col gap-3 sm:flex-row"
          onSubmit={(event) => {
            event.preventDefault();
            setResolved(null);
            setSelectedProfile(null);
            resolve.mutate(url.trim());
          }}
        >
          <label className="sr-only" htmlFor="makerworld-cn-url">Liên kết MakerWorld China</label>
          <input
            id="makerworld-cn-url"
            value={url}
            disabled={download.isPending || downloadAll.isPending}
            onChange={(event) => {
              setUrl(event.target.value);
              setResolved(null);
              setSelectedProfile(null);
            }}
            placeholder="https://makerworld.cn/zh/models/..."
            className="min-w-0 flex-1 rounded-md border border-bambu-gray-dark/40 bg-bambu-dark-secondary px-4 py-3 text-white outline-none focus:border-bambu-green"
          />
          <Button type="submit" disabled={!url.trim() || resolve.isPending || download.isPending || downloadAll.isPending}>
            {resolve.isPending ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}
            Xem mẫu
          </Button>
        </form>

        {error && (
          <div role="alert" className="mt-5 flex max-w-4xl items-start gap-3 border-l-2 border-status-error bg-bambu-dark-secondary px-4 py-3 text-sm">
            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-status-error" />
            <span>Không thể hoàn tất yêu cầu: {error.message}</span>
          </div>
        )}

        {resolved && (
          <section className="mt-8">
            <div className="flex flex-col gap-5 border-y border-bambu-gray-dark/30 py-5 sm:flex-row">
              {cover && <img src={cover} alt={title} className="aspect-[4/3] w-full bg-bambu-dark-secondary object-cover sm:w-44" />}
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0">
                    <h2 className="text-xl font-semibold text-white">{title}</h2>
                  {creator && <p className="mt-1 text-sm text-bambu-gray">Tác giả: {creator}</p>}
                  </div>
                </div>
                <div className="mt-3 flex flex-wrap gap-x-5 gap-y-2 text-xs text-bambu-gray">
                  <span>{instances.length} bàn in</span>
                  {downloads !== null && <span>{downloads.toLocaleString()} lượt tải</span>}
                  {license && <span>Giấy phép: {license}</span>}
                  <span>Mã mẫu {resolved.model_id}</span>
                </div>
                {summary && (
                  <div
                    className="makerworld-summary prose prose-sm mt-3 line-clamp-3 max-w-4xl overflow-hidden text-bambu-gray-light dark:prose-invert"
                    dangerouslySetInnerHTML={{ __html: safeHtml(summary) }}
                  />
                )}
                <a
                  className="mt-3 inline-flex items-center gap-1.5 text-xs text-bambu-gray-light hover:text-bambu-green"
                  href={`https://makerworld.cn/zh/models/${resolved.model_id}`}
                  target="_blank"
                  rel="noreferrer"
                >
                  <ExternalLink className="h-3.5 w-3.5" /> Mở trên MakerWorld
                </a>
              </div>
            </div>

            <div className="mt-7">
              <div role="tablist" aria-label="Nội dung mẫu MakerWorld" className="flex gap-1 overflow-x-auto border-b border-bambu-gray-dark/40">
                {([
                  ['plates', 'Các bàn in'],
                  ['guides', 'Tài liệu và hướng dẫn'],
                  ['description', 'Mô tả, giới thiệu'],
                  ['materials', 'Vật tư yêu cầu'],
                ] as const).map(([tab, label]) => (
                  <button
                    key={tab}
                    type="button"
                    role="tab"
                    id={`makerworld-tab-${tab}`}
                    aria-selected={activeTab === tab}
                    aria-controls={`makerworld-panel-${tab}`}
                    onClick={() => setActiveTab(tab)}
                    className={`whitespace-nowrap border-b-2 px-4 py-3 text-sm font-medium transition-colors ${activeTab === tab ? 'border-bambu-green text-white' : 'border-transparent text-bambu-gray hover:text-white'}`}
                  >
                    {label}
                  </button>
                ))}
              </div>
              <div role="tabpanel" id={`makerworld-panel-${activeTab}`} aria-labelledby={`makerworld-tab-${activeTab}`}>
            {activeTab === 'plates' && <>
              <div className="mb-3 flex flex-wrap items-end justify-between gap-3 border-b border-bambu-gray-dark/30 pb-3">
                <div>
                  <h2 className="text-lg font-semibold text-white">Các bàn in</h2>
                  <p className="mt-1 text-xs text-bambu-gray">Chọn một bàn in để tải riêng hoặc tải tất cả.</p>
                </div>
                <div className="flex flex-wrap items-center gap-3">
                  <span className="text-sm text-bambu-gray">{instances.length} cấu hình</span>
                  <Button
                    disabled={!instances.some((plate) => numberField(plate.profileId) !== null) || downloadAll.isPending || download.isPending}
                    onClick={() => downloadAll.mutate({
                      modelId: resolved.model_id,
                      plates: instances.filter((plate) => numberField(plate.profileId) !== null),
                    })}
                  >
                    {downloadAll.isPending ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />}
                    {batchProgress
                      ? `Đang tải ${batchProgress.current}/${batchProgress.total}…`
                      : downloadAll.isPending ? 'Đang tạo tệp ZIP…' : 'Tải tất cả (.ZIP)'}
                  </Button>
                </div>
              </div>
              <div className="divide-y divide-bambu-gray-dark/30">
                {instances.map((instance, index) => {
                  const profileId = numberField(instance.profileId);
                  const instanceTitle = textField(instance.title) || `Bàn in ${index + 1}`;
                  const active = profileId !== null && profileId === selectedProfile;
                  const thumb = imageUrl(textField(instance.cover) || textField(instance.thumbnailUrl));
                  const materialCount = numberField(instance.materialCnt);
                  const plateDownloads = numberField(instance.downloadCount);
                  const plateCount = numberField(instance.plateCount);
                  const printTimeSeconds = numberField(instance.printTimeSeconds);
                  const ratingScore = numberField(instance.ratingScoreTotal);
                  const ratingCount = numberField(instance.ratingCount);
                  const compatibility = instance.compatibility && typeof instance.compatibility === 'object'
                    ? textField((instance.compatibility as Record<string, unknown>).devProductName)
                    : '';
                  const otherCompatibility = Array.isArray(instance.otherCompatibility)
                    ? instance.otherCompatibility
                        .map((item) => item && typeof item === 'object' ? textField((item as Record<string, unknown>).devProductName) : '')
                        .filter(Boolean)
                    : [];
                  return (
                    <button
                      key={String(instance.id ?? profileId ?? index)}
                      type="button"
                      disabled={profileId === null}
                      onClick={() => setSelectedProfile(profileId)}
                      className={`flex w-full items-center gap-4 py-4 text-left transition-colors hover:bg-bambu-dark-secondary/50 ${active ? 'text-white' : 'text-bambu-gray-light'} disabled:opacity-50`}
                    >
                      {thumb ? (
                        <img src={thumb} alt="" className="h-16 w-16 shrink-0 bg-bambu-dark-secondary object-cover" loading="lazy" />
                      ) : (
                        <span className="h-16 w-16 shrink-0 bg-bambu-dark-secondary" />
                      )}
                      <span className="min-w-0 flex-1">
                        <span className="block truncate font-medium">{instanceTitle}</span>
                        <span className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-xs text-bambu-gray">
                          {compatibility && <span>Tối ưu cho {compatibility}</span>}
                          {materialCount !== null && <span>{materialCount} loại vật liệu</span>}
                          {instance.needAms === true && <span>Cần AMS</span>}
                          {plateDownloads !== null && <span>{plateDownloads.toLocaleString()} lượt tải</span>}
                          {printTimeSeconds !== null && printTimeSeconds > 0 && <span className="inline-flex items-center gap-1"><Clock3 className="h-3.5 w-3.5" />{formatPrintTime(printTimeSeconds)}</span>}
                          {plateCount !== null && <span className="inline-flex items-center gap-1"><PanelsTopLeft className="h-3.5 w-3.5" />{plateCount} bàn in</span>}
                          {ratingScore !== null && ratingCount !== null && ratingCount > 0 && <span className="inline-flex items-center gap-1"><Star className="h-3.5 w-3.5 fill-amber-400 text-amber-400" />{(ratingScore / ratingCount).toFixed(1)} ({ratingCount})</span>}
                          {!compatibility && <span>Cấu hình {profileId ?? 'không khả dụng'}</span>}
                        </span>
                        {otherCompatibility.length > 0 && (
                          <span className="mt-1 block truncate text-xs text-bambu-gray" title={otherCompatibility.join(', ')}>
                            Tương thích thêm: {otherCompatibility.slice(0, 6).join(', ')}{otherCompatibility.length > 6 ? '…' : ''}
                          </span>
                        )}
                      </span>
                      <span className={`h-4 w-4 shrink-0 rounded-full border ${active ? 'border-bambu-green bg-bambu-green ring-2 ring-bambu-dark ring-offset-2 ring-offset-bambu-green' : 'border-bambu-gray-dark'}`} />
                    </button>
                  );
                })}
                {instances.length === 0 && <p className="py-6 text-sm text-bambu-gray">Không tìm thấy cấu hình có thể tải.</p>}
              </div>
              <div className="mt-5 flex flex-wrap items-center justify-between gap-4 border-t border-bambu-gray-dark/30 pt-4">
                <span className="text-sm text-bambu-gray">{selected ? textField(selected.title) || `Cấu hình ${selectedProfile}` : 'Chọn một bàn in để tiếp tục'}</span>
                <Button
                  disabled={!selected || selectedProfile === null || download.isPending || downloadAll.isPending}
                  onClick={() => download.mutate({ modelId: resolved.model_id, profileId: selectedProfile! })}
                >
                  {download.isPending ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />}
                  {download.isPending ? 'Đang tải…' : 'Tải 3MF'}
                </Button>
              </div>
            </>}
            {activeTab === 'guides' && (
              <div className="py-5">
                <h2 className="mb-4 text-base font-semibold text-white">Tài liệu và hướng dẫn</h2>
                {guides.length > 0 ? (
                  <ul className="grid gap-3 sm:grid-cols-2">
                    {guides.map((guide, index) => {
                      const fileUrl = textField(guide.url);
                      const name = textField(guide.name) || `Tài liệu ${index + 1}`;
                      return (
                        <li key={`${fileUrl}-${index}`} className="flex min-w-0 items-center gap-3 border-b border-bambu-gray-dark/30 py-3">
                          <FileText className="h-8 w-8 shrink-0 text-rose-400" />
                          <span className="min-w-0 flex-1 truncate text-sm font-medium text-white" title={name}>{name}</span>
                          {fileUrl && <>
                            <a href={fileUrl} target="_blank" rel="noreferrer" aria-label={`Xem ${name}`} title="Xem tài liệu" className="p-2 text-bambu-gray hover:text-white"><Eye className="h-4 w-4" /></a>
                            <a href={fileUrl} download={name} aria-label={`Tải ${name}`} title="Tải tài liệu" className="p-2 text-bambu-gray hover:text-white"><Download className="h-4 w-4" /></a>
                          </>}
                        </li>
                      );
                    })}
                  </ul>
                ) : <p className="py-5 text-sm text-bambu-gray">Mẫu này chưa có tài liệu đính kèm.</p>}
              </div>
            )}
            {activeTab === 'description' && (
              <div className="py-5">
                <h2 className="mb-4 text-base font-semibold text-white">Mô tả, giới thiệu</h2>
                {summary ? (
                  <div
                    className="makerworld-summary prose prose-sm max-w-4xl text-bambu-gray-light dark:prose-invert"
                    dangerouslySetInnerHTML={{ __html: safeHtml(summary) }}
                  />
                ) : <p className="py-5 text-sm text-bambu-gray">Mẫu này chưa có mô tả.</p>}
              </div>
            )}
            {activeTab === 'materials' && (
              <div className="py-5">
                <h2 className="mb-4 text-base font-semibold text-white">Vật tư yêu cầu</h2>
                {materials.length > 0 ? (
                  <ul className="divide-y divide-bambu-gray-dark/30 rounded-md border border-bambu-gray-dark/40">
                    {materials.map((material, index) => {
                      const image = imageUrl(textField(material.image));
                      const title = textField(material.displayParentTitle) || textField(material.parentTitle) || textField(material.displayTitle) || textField(material.title) || `Vật tư ${index + 1}`;
                      const variant = textField(material.displayTitle) || textField(material.title);
                      const quantity = numberField(material.quantity);
                      const url = textField(material.url);
                      return (
                        <li key={`${textField(material.sku)}-${index}`} className="flex items-center gap-3 px-4 py-3">
                          {image ? <img src={image} alt="" className="h-10 w-10 shrink-0 rounded-md bg-white object-contain" loading="lazy" /> : <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-md bg-bambu-dark-secondary"><PanelsTopLeft className="h-4 w-4 text-bambu-gray" /></span>}
                          <span className="min-w-0 flex-1">
                            <span className="block truncate text-sm font-medium text-white">{title}</span>
                            {variant && variant !== title && <span className="block truncate text-xs text-bambu-gray">{variant}</span>}
                          </span>
                          <span className="text-xs text-bambu-gray">x{quantity ?? 1}</span>
                          {url && <a href={url} target="_blank" rel="noreferrer" aria-label={`Mở ${title}`} title="Mở sản phẩm" className="p-2 text-bambu-gray hover:text-white"><ExternalLink className="h-4 w-4" /></a>}
                        </li>
                      );
                    })}
                  </ul>
                ) : <p className="py-5 text-sm text-bambu-gray">Mẫu này chưa có danh sách vật tư.</p>}
              </div>
            )}
              </div>
            </div>
          </section>
        )}
      </div>
      <footer className="border-t border-bambu-gray-dark/30 px-5 py-5 text-center text-xs text-bambu-gray">
        © 2026. Bản quyền thuộc về DM2026.
        <span className="mx-2" aria-hidden="true">·</span>
        Phiên bản v{versionQuery.data?.display_version || versionQuery.data?.version || 'đang kiểm tra'}
      </footer>
    </main>
  );
}
