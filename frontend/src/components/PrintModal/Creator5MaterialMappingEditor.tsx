import { AlertTriangle } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import type { Creator5MaterialMapping, PrinterStatus } from '../../api/client';
import type { FilamentReqsData } from './types';

type ToolMetadata = NonNullable<FilamentReqsData['creator5_tools']>[number];
type MaterialSlot = NonNullable<PrinterStatus['creator5_material_slots']>[number];

interface Props {
  tools: ToolMetadata[];
  slots: MaterialSlot[];
  warning?: string | null;
  mappings: Creator5MaterialMapping[];
  onChange: (mappings: Creator5MaterialMapping[]) => void;
}

const COLOR_RE = /^#[0-9a-f]{6}$/i;

export function isCreator5MappingComplete(
  tools: ToolMetadata[],
  slots: MaterialSlot[],
  mappings: Creator5MaterialMapping[],
): boolean {
  if (tools.length < 2 || tools.length > 4 || mappings.length !== tools.length) return false;
  const toolIds = new Set(mappings.map((mapping) => mapping.toolId));
  const slotIds = new Set(mappings.map((mapping) => mapping.slotId));
  if (toolIds.size !== tools.length || slotIds.size !== tools.length) return false;
  return tools.every((tool) => {
    const mapping = mappings.find((entry) => entry.toolId === tool.tool_id);
    const slot = slots.find((entry) => entry.slot_id === mapping?.slotId);
    return Boolean(
      mapping &&
      slot &&
      mapping.materialName.trim() &&
      COLOR_RE.test(mapping.toolMaterialColor) &&
      mapping.slotMaterialColor.toUpperCase() === slot.material_color.toUpperCase(),
    );
  });
}

export function Creator5MaterialMappingEditor({ tools, slots, warning, mappings, onChange }: Props) {
  const { t } = useTranslation();
  if (tools.length < 2) {
    if (!warning) return null;
    return (
      <div className="flex items-start gap-2 rounded border border-amber-500/30 bg-amber-500/10 p-2 text-xs text-amber-300">
        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
        <span>{warning}</span>
      </div>
    );
  }

  const update = (tool: ToolMetadata, patch: Partial<Creator5MaterialMapping>) => {
    const current = mappings.find((entry) => entry.toolId === tool.tool_id);
    const next: Creator5MaterialMapping = {
      toolId: tool.tool_id,
      slotId: current?.slotId ?? 0,
      materialName: current?.materialName ?? tool.material_name ?? '',
      toolMaterialColor: current?.toolMaterialColor ?? tool.tool_material_color ?? '',
      slotMaterialColor: current?.slotMaterialColor ?? '',
      ...patch,
    };
    onChange([...mappings.filter((entry) => entry.toolId !== tool.tool_id), next].sort((a, b) => a.toolId - b.toolId));
  };

  return (
    <section className="space-y-3 border-t border-bambu-dark-tertiary pt-4" aria-labelledby="creator5-mapping-title">
      <div className="space-y-1">
        <h3 id="creator5-mapping-title" className="text-sm font-medium text-white">
          {t('printModal.creator5Mapping.title', 'Creator 5 material mapping')}
        </h3>
        <p className="text-xs text-bambu-gray">
          {t('printModal.creator5Mapping.description', 'Assign each G-code tool to a distinct material station slot.')}
        </p>
      </div>

      {warning && (
        <div className="flex items-start gap-2 rounded border border-amber-500/30 bg-amber-500/10 p-2 text-xs text-amber-300">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          <span>{warning}</span>
        </div>
      )}

      {slots.length === 0 && (
        <div className="flex items-start gap-2 rounded border border-amber-500/30 bg-amber-500/10 p-2 text-xs text-amber-300">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          <span>{t('printModal.creator5Mapping.noSlots', 'Material station slot details are unavailable.')}</span>
        </div>
      )}

      <div className="divide-y divide-bambu-dark-tertiary">
        {tools.map((tool) => {
          const mapping = mappings.find((entry) => entry.toolId === tool.tool_id);
          const usedSlots = new Set(mappings.filter((entry) => entry.toolId !== tool.tool_id).map((entry) => entry.slotId));
          const selectedSlot = slots.find((slot) => slot.slot_id === mapping?.slotId);
          const id = `creator5-tool-${tool.tool_id}`;
          return (
            <div key={tool.tool_id} className="grid grid-cols-1 gap-2 py-3 md:grid-cols-[5rem_minmax(9rem,1fr)_minmax(9rem,1fr)_minmax(10rem,1fr)] md:items-end">
              <div className="text-sm text-white">
                {t('printModal.creator5Mapping.tool', 'Tool')} {tool.tool_id}
              </div>
              <label className="block text-xs text-bambu-gray" htmlFor={`${id}-material`}>
                {t('printModal.creator5Mapping.material', 'G-code material')}
                <input
                  id={`${id}-material`}
                  value={mapping?.materialName ?? tool.material_name ?? ''}
                  onChange={(event) => update(tool, { materialName: event.target.value.slice(0, 32) })}
                  maxLength={32}
                  className="mt-1 block h-9 w-full rounded border border-bambu-dark-tertiary bg-bambu-dark px-2 text-sm text-white"
                />
              </label>
              <label className="block text-xs text-bambu-gray" htmlFor={`${id}-color`}>
                {t('printModal.creator5Mapping.toolColor', 'G-code color')}
                <input
                  id={`${id}-color`}
                  value={mapping?.toolMaterialColor ?? tool.tool_material_color ?? ''}
                  onChange={(event) => update(tool, { toolMaterialColor: event.target.value.slice(0, 7).toUpperCase() })}
                  maxLength={7}
                  placeholder="#RRGGBB"
                  className="mt-1 block h-9 w-full rounded border border-bambu-dark-tertiary bg-bambu-dark px-2 text-sm text-white"
                />
              </label>
              <label className="block text-xs text-bambu-gray" htmlFor={`${id}-slot`}>
                {t('printModal.creator5Mapping.slot', 'Material station slot')}
                <select
                  id={`${id}-slot`}
                  value={mapping?.slotId ?? 0}
                  onChange={(event) => {
                    const slotId = Number(event.target.value);
                    const slot = slots.find((entry) => entry.slot_id === slotId);
                    update(tool, { slotId, slotMaterialColor: slot?.material_color ?? '' });
                  }}
                  className="mt-1 block h-9 w-full rounded border border-bambu-dark-tertiary bg-bambu-dark px-2 text-sm text-white"
                >
                  <option value={0}>{t('printModal.creator5Mapping.chooseSlot', 'Select a slot')}</option>
                  {slots.map((slot) => (
                    <option key={slot.slot_id} value={slot.slot_id} disabled={usedSlots.has(slot.slot_id)}>
                      {slot.slot_id}: {slot.material_name} ({slot.material_color})
                    </option>
                  ))}
                </select>
                {selectedSlot && (
                  <span className="mt-1 flex items-center gap-1.5 text-[11px]">
                    <span className="h-3 w-3 rounded-sm border border-white/20" style={{ backgroundColor: selectedSlot.material_color }} />
                    {selectedSlot.material_name}, {selectedSlot.material_color}
                  </span>
                )}
              </label>
            </div>
          );
        })}
      </div>
    </section>
  );
}
