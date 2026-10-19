import { useState } from 'react';
import { AlertCircle, Download, ExternalLink, LoaderCircle, Search } from 'lucide-react';
import { useMutation } from '@tanstack/react-query';
import { api, type MakerworldResolvedModel } from '../api/client';
import { Button } from '../components/Button';

function textField(value: unknown): string {
  return typeof value === 'string' ? value : '';
}

function imageUrl(value: string): string {
  if (!/^https?:\/\/(?:makerworld|public-cdn)\.bblmw\.(?:com|cn)\//i.test(value)) return '';
  return `/api/v1/makerworld/thumbnail?url=${encodeURIComponent(value)}`;
}

export function MakerworldChinaPublicPage() {
  const [url, setUrl] = useState('');
  const [resolved, setResolved] = useState<MakerworldResolvedModel | null>(null);
  const [selectedProfile, setSelectedProfile] = useState<number | null>(null);
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

  const design = resolved?.design;
  const title = textField(design?.title) || 'MakerWorld model';
  const cover = imageUrl(textField(design?.coverUrl));
  const creator = design?.designCreator && typeof design.designCreator === 'object'
    ? textField((design.designCreator as Record<string, unknown>).name)
    : '';
  const instances = resolved?.instances ?? [];
  const selected = instances.find((item) => item.profileId === selectedProfile);
  const error = resolve.error ?? download.error;

  return (
    <main className="min-h-screen bg-bambu-dark text-bambu-gray-light">
      <header className="border-b border-bambu-gray-dark/30">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-5 py-4">
          <a href="/" className="font-semibold tracking-wide text-white">Printbuddy</a>
          <span className="inline-flex items-center gap-2 text-sm text-bambu-gray">
            <span className="h-2 w-2 rounded-full bg-status-ok" /> MakerWorld China
          </span>
        </div>
      </header>

      <div className="mx-auto max-w-6xl px-5 pb-16 pt-10">
        <div className="mb-8 max-w-3xl">
          <h1 className="text-3xl font-semibold text-white">Download MakerWorld China models</h1>
          <p className="mt-2 text-bambu-gray">Paste a MakerWorld China model link to preview its plates and download a 3MF.</p>
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
          <label className="sr-only" htmlFor="makerworld-cn-url">MakerWorld China URL</label>
          <input
            id="makerworld-cn-url"
            value={url}
            onChange={(event) => {
              setUrl(event.target.value);
              setResolved(null);
              setSelectedProfile(null);
            }}
            placeholder="https://makerworld.cn/zh/models/..."
            className="min-w-0 flex-1 rounded-md border border-bambu-gray-dark/40 bg-bambu-dark-secondary px-4 py-3 text-white outline-none focus:border-bambu-green"
          />
          <Button type="submit" disabled={!url.trim() || resolve.isPending}>
            {resolve.isPending ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}
            Preview
          </Button>
        </form>

        {error && (
          <div role="alert" className="mt-5 flex max-w-4xl items-start gap-3 border-l-2 border-status-error bg-bambu-dark-secondary px-4 py-3 text-sm">
            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-status-error" />
            <span>{error.message}</span>
          </div>
        )}

        {resolved && (
          <section className="mt-10 grid gap-8 lg:grid-cols-[minmax(0,1fr)_340px]">
            <div>
              <div className="mb-5 flex flex-wrap items-end justify-between gap-3 border-b border-bambu-gray-dark/30 pb-3">
                <div>
                  <h2 className="text-xl font-semibold text-white">Plates</h2>
                  <p className="mt-1 text-sm text-bambu-gray">{instances.length} available</p>
                </div>
                <a
                  className="inline-flex items-center gap-1.5 text-sm text-bambu-green hover:underline"
                  href={`https://makerworld.cn/zh/models/${resolved.model_id}`}
                  target="_blank"
                  rel="noreferrer"
                >
                  Open on MakerWorld <ExternalLink className="h-3.5 w-3.5" />
                </a>
              </div>
              <div className="divide-y divide-bambu-gray-dark/30">
                {instances.map((instance, index) => {
                  const profileId = typeof instance.profileId === 'number' ? instance.profileId : null;
                  const instanceTitle = textField(instance.title) || `Plate ${index + 1}`;
                  const active = profileId !== null && profileId === selectedProfile;
                  return (
                    <button
                      key={String(instance.id ?? profileId ?? index)}
                      type="button"
                      disabled={profileId === null}
                      onClick={() => setSelectedProfile(profileId)}
                      className={`flex min-h-16 w-full items-center justify-between gap-4 py-4 text-left ${active ? 'text-white' : 'text-bambu-gray-light'} disabled:opacity-50`}
                    >
                      <span className="min-w-0">
                        <span className="block truncate font-medium">{instanceTitle}</span>
                        <span className="mt-1 block text-xs text-bambu-gray">Profile {profileId ?? 'unavailable'}</span>
                      </span>
                      <span className={`h-4 w-4 shrink-0 rounded-full border ${active ? 'border-bambu-green bg-bambu-green ring-2 ring-bambu-dark ring-offset-2 ring-offset-bambu-green' : 'border-bambu-gray-dark'}`} />
                    </button>
                  );
                })}
                {instances.length === 0 && <p className="py-6 text-sm text-bambu-gray">No downloadable plates were returned.</p>}
              </div>
            </div>

            <aside className="self-start border-t-2 border-bambu-green pt-4">
              {cover && <img src={cover} alt={title} className="mb-4 aspect-[4/3] w-full bg-bambu-dark-secondary object-cover" />}
              <h2 className="text-lg font-semibold text-white">{title}</h2>
              {creator && <p className="mt-1 text-sm text-bambu-gray">by {creator}</p>}
              <Button
                className="mt-5 w-full"
                disabled={!selected || selectedProfile === null || download.isPending}
                onClick={() => download.mutate({ modelId: resolved.model_id, profileId: selectedProfile! })}
              >
                {download.isPending ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />}
                {download.isPending ? 'Downloading…' : 'Download 3MF'}
              </Button>
            </aside>
          </section>
        )}
      </div>
    </main>
  );
}
