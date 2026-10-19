import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { SupportPage } from '../../pages/SupportPage';

describe('SupportPage', () => {
  it('shows the support details, QR image, and return link', () => {
    render(<SupportPage />);

    expect(screen.getByRole('heading', { name: 'Ủng hộ tác giả' })).toBeInTheDocument();
    expect(screen.getByText('LÊ QUỐC ANH')).toBeInTheDocument();
    expect(screen.getByRole('img', { name: /Mã QR ủng hộ tác giả/ })).toHaveAttribute('src', '/img/donation-qr.jpg');
    expect(screen.getByRole('link', { name: 'MakerWorld China' })).toHaveAttribute('href', '/makerworld-cn');
  });
});
