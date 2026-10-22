import { describe, expect, it } from 'vitest';
import type { Creator5MaterialMapping, PrinterStatus } from '../../api/client';
import { isCreator5MappingComplete } from '../../components/PrintModal/Creator5MaterialMappingEditor';
import type { FilamentReqsData } from '../../components/PrintModal/types';

const tools: NonNullable<FilamentReqsData['creator5_tools']> = [
  { tool_id: 0, material_name: 'PLA', tool_material_color: '#FFFFFF' },
  { tool_id: 2, material_name: 'PETG', tool_material_color: '#F82D29' },
];

const slots: NonNullable<PrinterStatus['creator5_material_slots']> = [
  { slot_id: 1, material_name: 'PLA', material_color: '#FFFFFF' },
  { slot_id: 3, material_name: 'PETG', material_color: '#F82D29' },
];

const mappings: Creator5MaterialMapping[] = [
  { toolId: 0, slotId: 3, materialName: 'PLA', toolMaterialColor: '#FFFFFF', slotMaterialColor: '#F82D29' },
  { toolId: 2, slotId: 1, materialName: 'PETG', toolMaterialColor: '#F82D29', slotMaterialColor: '#FFFFFF' },
];

describe('Creator 5 queue material mappings', () => {
  it('accepts exact logical tool coverage with distinct available physical slots', () => {
    expect(isCreator5MappingComplete(tools, slots, mappings)).toBe(true);
  });

  it('rejects missing tools, duplicate physical slots, and stale slot colors', () => {
    expect(isCreator5MappingComplete(tools, slots, [mappings[0]])).toBe(false);
    expect(isCreator5MappingComplete(tools, slots, [mappings[0], { ...mappings[1], slotId: 3 }])).toBe(false);
    expect(isCreator5MappingComplete(tools, slots, [mappings[0], { ...mappings[1], slotMaterialColor: '#000000' }])).toBe(false);
  });
});
