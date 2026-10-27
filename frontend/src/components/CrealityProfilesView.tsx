import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Download, Loader2, Search } from 'lucide-react';
import { api } from '../api/client';
import { Card, CardContent } from './Card';

type ProfileKind = 'printer' | 'process' | 'filament';

export function CrealityProfilesView() {
  const { t } = useTranslation();
  const [kind, setKind] = useState<ProfileKind>('printer');
  const [printer, setPrinter] = useState('');
  const [nozzle, setNozzle] = useState('');
  const [search, setSearch] = useState('');
  const [selectedId, setSelectedId] = useState('');
  const catalog = useQuery({
    queryKey: ['crealityProfiles', kind, printer, nozzle, search],
    queryFn: () => api.getCrealityProfiles({ kind, printer: printer || undefined, nozzle: nozzle || undefined, search: search || undefined }),
  });
  const detail = useQuery({
    queryKey: ['crealityProfile', selectedId],
    queryFn: () => api.getCrealityProfileDetail(selectedId),
    enabled: Boolean(selectedId),
  });
  const profiles = catalog.data?.profiles ?? [];
  const nozzles = useMemo(() => [...new Set(profiles.flatMap(profile => profile.nozzles))].sort(), [profiles]);

  const download = () => {
    if (!detail.data) return;
    const blob = new Blob([JSON.stringify(detail.data.setting, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `${detail.data.name}.json`;
    link.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex rounded-md border border-bambu-dark-tertiary p-1">
          {(['printer', 'process', 'filament'] as const).map(value => (
            <button key={value} onClick={() => { setKind(value); setSelectedId(''); }} className={`px-3 py-1.5 text-sm rounded ${kind === value ? 'bg-bambu-green text-black' : 'text-bambu-gray hover:text-white'}`}>
              {{ printer: t('profiles.creality.kind.printer'), process: t('profiles.creality.kind.process'), filament: t('profiles.creality.kind.filament') }[value]}
            </button>
          ))}
        </div>
        <select aria-label="Model máy in" value={printer} onChange={event => { setPrinter(event.target.value); setSelectedId(''); }} className="bg-bambu-dark border border-bambu-dark-tertiary rounded px-3 py-2 text-sm text-white">
          <option value="">{t('profiles.creality.allModels')}</option>
          {(catalog.data?.printers ?? []).map(value => <option key={value}>{value}</option>)}
        </select>
        <select aria-label="Đường kính nozzle" value={nozzle} onChange={event => { setNozzle(event.target.value); setSelectedId(''); }} className="bg-bambu-dark border border-bambu-dark-tertiary rounded px-3 py-2 text-sm text-white">
          <option value="">{t('profiles.creality.allNozzles')}</option>
          {nozzles.map(value => <option key={value} value={value}>{value} mm</option>)}
        </select>
        <label className="relative flex-1 min-w-48">
          <Search className="w-4 h-4 absolute left-3 top-2.5 text-bambu-gray" />
          <input value={search} onChange={event => setSearch(event.target.value)} placeholder={t('profiles.creality.search')} className="w-full bg-bambu-dark border border-bambu-dark-tertiary rounded pl-9 pr-3 py-2 text-sm text-white" />
        </label>
      </div>

      <p className="text-xs text-bambu-gray">{t('profiles.creality.source', { source: catalog.data?.source, license: catalog.data?.license })}</p>
      {catalog.isLoading ? <div className="py-12 flex justify-center"><Loader2 className="w-6 h-6 animate-spin text-bambu-green" /></div> : catalog.error ? <p className="text-red-400">{(catalog.error as Error).message}</p> : (
        <div className="grid grid-cols-1 xl:grid-cols-[minmax(0,1fr)_minmax(360px,0.9fr)] gap-4">
          <Card><CardContent className="p-3 max-h-[65vh] overflow-auto">
            <p className="text-xs text-bambu-gray px-2 pb-2">{t('profiles.creality.count', { count: profiles.length })}</p>
            <div className="space-y-1">{profiles.map(profile => <button key={profile.id} onClick={() => setSelectedId(profile.id)} className={`w-full text-left rounded px-3 py-2 ${selectedId === profile.id ? 'bg-bambu-green/15 border border-bambu-green/40' : 'hover:bg-bambu-dark'}`}>
              <span className="block text-sm text-white">{profile.name}</span>
              <span className="block text-xs text-bambu-gray mt-1">{profile.printer || 'Creality'}{profile.nozzles.length ? ` · ${profile.nozzles.join(', ')} mm` : ''}{profile.inherits ? ` · inherits ${profile.inherits}` : ''}</span>
            </button>)}</div>
          </CardContent></Card>
          <Card><CardContent className="p-4">
            {!selectedId ? <p className="text-sm text-bambu-gray">{t('profiles.creality.selectProfile')}</p> : detail.isLoading ? <Loader2 className="w-5 h-5 animate-spin text-bambu-green" /> : detail.data ? <>
              <div className="flex items-start justify-between gap-3 mb-3"><div><h3 className="font-medium text-white">{detail.data.name}</h3><p className="text-xs text-bambu-gray mt-1">{detail.data.inherits ? t('profiles.creality.inherits', { name: detail.data.inherits }) : t('profiles.creality.baseProfile')}</p></div><button title={t('profiles.creality.download')} onClick={download} className="p-2 text-bambu-gray hover:text-white" aria-label={t('profiles.creality.download')}><Download className="w-4 h-4" /></button></div>
              <pre className="max-h-[55vh] overflow-auto rounded bg-bambu-dark p-3 text-xs text-bambu-gray whitespace-pre-wrap">{JSON.stringify(detail.data.setting, null, 2)}</pre>
            </> : null}
          </CardContent></Card>
        </div>
      )}
    </div>
  );
}
