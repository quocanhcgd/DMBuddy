import { ArrowLeft, Heart, ShieldCheck } from 'lucide-react';

export function SupportPage() {
  return (
    <main className="min-h-screen bg-bambu-dark text-bambu-gray-light">
      <header className="border-b border-bambu-gray-dark/30">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-5 py-4">
          <a href="/" className="font-semibold tracking-wide text-white">DMbuddy</a>
          <a
            href="/makerworld-cn"
            className="inline-flex min-h-10 items-center gap-2 rounded-md border border-bambu-gray-dark/50 px-3 text-sm font-medium text-white transition-colors hover:border-bambu-green/60 hover:text-bambu-green"
          >
            <ArrowLeft className="h-4 w-4" />
            MakerWorld China
          </a>
        </div>
      </header>

      <div className="mx-auto grid max-w-6xl items-center gap-10 px-5 py-10 md:grid-cols-[minmax(0,1fr)_minmax(280px,390px)] md:gap-16 md:py-16">
        <section className="max-w-2xl">
          <div className="mb-5 inline-flex h-11 w-11 items-center justify-center rounded-lg border border-rose-300/20 bg-rose-400/10 text-rose-300">
            <Heart className="h-5 w-5" />
          </div>
          <h1 className="text-3xl font-semibold text-white">Ủng hộ tác giả</h1>
          <p className="mt-4 text-base leading-7 text-bambu-gray-light">
            3DHubvn.net được xây dựng để tập hợp các công cụ hữu ích giúp việc quản lý máy in 3D và tải mẫu thuận tiện hơn. Nếu công cụ này hữu ích với bạn, một khoản ủng hộ tự nguyện sẽ giúp tác giả duy trì máy chủ, phát triển tính năng và tiếp tục cải thiện sản phẩm.
          </p>
          <p className="mt-4 text-sm leading-6 text-bambu-gray">
            Quét mã QR bằng ứng dụng ngân hàng hoặc ví điện tử có hỗ trợ chuyển khoản. Mọi mức ủng hộ đều được trân trọng; việc ủng hộ hoàn toàn tùy ý và không ảnh hưởng đến quyền sử dụng DMbuddy.
          </p>

          <div className="mt-8 flex items-start gap-3 border-t border-bambu-gray-dark/40 pt-5 text-sm text-bambu-gray">
            <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-bambu-green" />
            <p>Kiểm tra tên người nhận <span className="font-medium text-white">LÊ QUỐC ANH</span> trong ứng dụng trước khi xác nhận giao dịch.</p>
          </div>
        </section>

        <section className="mx-auto w-full max-w-[390px]">
          <div className="overflow-hidden rounded-lg border border-bambu-gray-dark/40 bg-white shadow-xl shadow-black/20">
            <img
              src="/img/donation-qr.jpg"
              alt="Mã QR ủng hộ tác giả Lê Quốc Anh qua các ứng dụng chuyển tiền"
              className="block h-auto w-full"
            />
          </div>
          <p className="mt-3 text-center text-xs text-bambu-gray">Mã QR nhận tiền từ các ứng dụng chuyển tiền</p>
        </section>
      </div>

      <footer className="border-t border-bambu-gray-dark/30 px-5 py-5 text-center text-xs text-bambu-gray">
        © 2026. Bản quyền thuộc về DM2026.
      </footer>
    </main>
  );
}
