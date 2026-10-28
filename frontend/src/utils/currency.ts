import i18n from '../i18n';

const CURRENCY_SYMBOLS: Record<string, string> = {
  USD: '$',
  EUR: '€',
  GBP: '£',
  CHF: 'Fr.',
  JPY: '¥',
  CNY: '¥',
  CAD: '$',
  AUD: '$',
  INR: '₹',
  HKD: 'HK$',
  KRW: '₩',
  SEK: 'kr',
  NOK: 'kr',
  DKK: 'kr',
  PLN: 'zł',
  BRL: 'R$',
  TWD: 'NT$',
  SGD: 'S$',
  NZD: 'NZ$',
  MXN: 'MX$',
  BZD: 'BZ$',
  MYR: 'RM',
  CZK: 'Kč',
  THB: '฿',
  ZAR: 'R',
  TRY: '₺',
  RUB: '₽',
  HUF: 'Ft',
  ILS: '₪',
  UAH: '₴',
  VND: '₫',
};

export function getCurrencySymbol(currencyCode: string): string {
  return CURRENCY_SYMBOLS[currencyCode.toUpperCase()] || currencyCode;
}

const LOCALE_BY_LANGUAGE: Record<string, string> = {
  vi: 'vi-VN',
  en: 'en-US',
  de: 'de-DE',
  es: 'es-ES',
  fr: 'fr-FR',
  it: 'it-IT',
  ja: 'ja-JP',
  ko: 'ko-KR',
  pt: 'pt-BR',
  zh: 'zh-CN',
};

export function formatCurrency(amount: number | null | undefined, currencyCode: string, locale?: string): string {
  const currency = currencyCode.toUpperCase();
  const activeLocale = locale || i18n.resolvedLanguage || i18n.language || 'en-US';
  const normalizedLocale = LOCALE_BY_LANGUAGE[activeLocale] || activeLocale;
  return new Intl.NumberFormat(normalizedLocale, {
    style: 'currency',
    currency,
    currencyDisplay: 'symbol',
  }).format(amount ?? 0);
}

export const SUPPORTED_CURRENCIES = Object.entries(CURRENCY_SYMBOLS).map(([code, symbol]) => ({
  code,
  label: `${code} (${symbol})`,
}));
