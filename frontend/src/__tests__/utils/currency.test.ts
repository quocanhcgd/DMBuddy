import { describe, it, expect } from 'vitest';
import { formatCurrency, getCurrencySymbol, SUPPORTED_CURRENCIES } from '../../utils/currency';

describe('getCurrencySymbol', () => {
  it('returns $ for USD', () => {
    expect(getCurrencySymbol('USD')).toBe('$');
  });

  it('returns € for EUR', () => {
    expect(getCurrencySymbol('EUR')).toBe('€');
  });

  it('returns £ for GBP', () => {
    expect(getCurrencySymbol('GBP')).toBe('£');
  });

  it('returns ₹ for INR', () => {
    expect(getCurrencySymbol('INR')).toBe('₹');
  });

  it('returns HK$ for HKD', () => {
    expect(getCurrencySymbol('HKD')).toBe('HK$');
  });

  it('returns RM for MYR', () => {
    expect(getCurrencySymbol('MYR')).toBe('RM');
  });

  it('returns ₴ for UAH', () => {
    expect(getCurrencySymbol('UAH')).toBe('₴');
  });

  it('returns BZ$ for BZD', () => {
    expect(getCurrencySymbol('BZD')).toBe('BZ$');
  });

  it('returns ₫ for VND', () => {
    expect(getCurrencySymbol('VND')).toBe('₫');
  });

  it('returns the code itself for unknown currencies', () => {
    expect(getCurrencySymbol('XYZ')).toBe('XYZ');
  });

  it('is case-insensitive', () => {
    expect(getCurrencySymbol('usd')).toBe('$');
    expect(getCurrencySymbol('eur')).toBe('€');
  });
});

describe('SUPPORTED_CURRENCIES', () => {
  it('contains INR', () => {
    expect(SUPPORTED_CURRENCIES.find((c) => c.code === 'INR')).toBeDefined();
  });

  it('contains MYR', () => {
    expect(SUPPORTED_CURRENCIES.find((c) => c.code === 'MYR')).toBeDefined();
  });

  it('contains BZD', () => {
    expect(SUPPORTED_CURRENCIES.find((c) => c.code === 'BZD')).toBeDefined();
  });

  it('includes Vietnamese dong with its symbol', () => {
    expect(SUPPORTED_CURRENCIES.find((c) => c.code === 'VND')).toEqual({
      code: 'VND',
      label: 'VND (₫)',
    });
  });

  it('has 31 entries', () => {
    expect(SUPPORTED_CURRENCIES).toHaveLength(31);
  });
});

describe('formatCurrency', () => {
  it('formats VND with Vietnamese separators, no decimal places, and the symbol after the amount', () => {
    expect(formatCurrency(1234567.89, 'VND', 'vi')).toBe('1.234.568 ₫');
  });

  it('formats USD according to the active locale', () => {
    expect(formatCurrency(1234567.89, 'USD', 'en')).toBe('$1,234,567.89');
    expect(formatCurrency(1234567.89, 'USD', 'de')).toBe('1.234.567,89 $');
  });
});
