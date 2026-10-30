import { describe, expect, it } from 'vitest';
import { PRINTER_MODEL_GROUPS } from '../../utils/printerModels';

describe('printer model catalog', () => {
  it('lists Creality K3 under the Klipper printer group', () => {
    const group = PRINTER_MODEL_GROUPS.find((entry) => entry.label === 'Creality Klipper');

    expect(group?.options).toContainEqual({ value: 'Creality K3', label: 'K3' });
    expect(group?.options).toContainEqual({ value: 'Creality SPARKX i7', label: 'SPARKX i7' });
    expect(group?.options).toContainEqual({ value: 'Creality SPARKX i8', label: 'SPARKX i8' });
  });
});
