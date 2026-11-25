# Roadmap

Seri baru Woof Cleaner dimulai dari **0.1.0** pada 25 November 2026 dengan fitur yang sudah ada. Versi stabil pertama adalah **1.0.0**. Tabel berikut mencatat kondisi baseline 0.1.0. Milestone di bawahnya mengikuti [alur aplikasi](../AGENTS.md) dan [riset CCleaner](CCLEANER_RESEARCH.md).

Legend: ✅ done · ◐ partly · ❌ not yet

| Area | Woof 0.1.0 |
|---|---|
| Rule-based junk cleaning (75 rules: Windows, browsers, apps, AI tools, Store apps, developer caches) | ✅ |
| Browser history, downloads, cookies (with allowlist), form data, row by row | ✅ |
| Saved passwords / cards cleaning | ❌ deliberately not offered |
| Secure deletion, alternate data streams, wipe free space | ❌ |
| Include / exclude your own folders from the UI | ❌ (edit `rules.ini`) |
| Export results to CSV | ❌ |
| Registry cleaner | ◐ 10 categories; services, type libraries, firewall rules and file associations are deliberately left out |
| Startup apps, scheduled tasks, Windows services, context menu | ✅ |
| Uninstaller with leftover sweep | ✅ |
| Temporary uninstall (restore within N days) | ❌ |
| Software updates with skip / ignore | ✅ |
| Driver updates with skip / ignore | ✅ |
| Driver rollback, "what is wrong" troubleshooting wizard | ❌ |
| Duplicate finder | ◐ type filter; no CSV export |
| Disk space per file type | ❌ |
| Scheduled cleaning (daily / weekly / every 2 weeks / sign-in) | ✅ |
| One-click health check with a score | ❌ |
| Statistics over time | ◐ history of automatic cleans |
| Background-app sleep mode | ❌ |
| Cloud storage cleaning (Google Drive, OneDrive, Dropbox) | ❌ |
| Themes, start without UAC prompt, self-update | ✅ |
| Tray icon, languages | ❌ |

## Milestone dan TODO

Implementasi B01–B12 tersedia dalam kandidat lokal 0.4.0. R01–R05 menghasilkan [keputusan kelayakan](FEASIBILITY.md). Pengguna mengonfirmasi pengujian kandidat selesai dan menyetujui rilis 1.0.0. B13 dan B14 ditutup berdasarkan konfirmasi tersebut. Usulan 1.1 mencakup alur Custom Clean dalam Bahasa Indonesia dan ikon tray opsional.

### Hasil pengujian kandidat 0.4.0

| Pemeriksaan | Hasil pada PC proyek |
|---|---|
| Engine, SQLite, restore, jadwal, duplikat, CSV dan updater | 50 tes lulus dengan `python -m unittest discover -s tests`. Fixture memakai folder sementara dan key HKCU khusus. Updater diuji dengan server lokal dan checksum benar, salah, serta hilang. [Tes alur](../tests/test_workflows.py) dan [tes updater](../tests/test_update.py) |
| Waktu sampai Analyze merespons klik | Lima peluncuran EXE per versi. Baseline 0.1.0 menghasilkan 1298, 1549, 1552, 1441, 1909 ms (median 1549 ms). Build uji 0.4.0 menghasilkan 1071, 918, 883, 1464, 1355 ms (median 1071 ms). Pengukuran berakhir ketika Analyze membuka dialog pilihan kosong. |
| Jendela dan aksesibilitas | Kedua tema diperiksa pada 1240 × 780 dan 904 × 478 dengan skala Tk yang menyimulasikan 100% dan 150%. Uji mencakup maximize/restore, dua label Indonesia panjang, navigasi keyboard, Space, dan Esc dengan fokus kembali ke Run Cleaner. Rasio kontras tombol utama terang/gelap 6,31:1 dan 7,42:1. Teks sekunder 4,50:1 dan 5,69:1. Angka di sini berasal dari simulasi skala Tk. |
| Respons tabel dan pembatalan | Pada fixture 10.000 baris, jeda event loop persentil ke-95 sebesar 25,45 ms. Handler Stop mengubah status menjadi Cancelling dalam 0,17 ms. Waktu hingga worker berhenti bergantung pada operasi yang sedang berjalan. |
| Health Check dan penggunaan ruang | Tampilan Health Check diuji dengan hasil kosong, temuan browser terkunci, serta pembatalan. Tes penggunaan disk membandingkan total byte dan melaporkan path junction yang dilewati. |
| Paket Windows | GUI dan CLI portable lulus dengan Python dikeluarkan dari PATH. Analyze, Clean, restore dan auto-clean memakai fixture. Properti versi ketiga EXE menunjukkan 0.4.0 dan semua hash cocok dengan manifest. |

Ulangi uji paket dari root repo. Mode `CurrentUser` dan `AllUsers` masing-masing membutuhkan snapshot Windows 11 bersih tanpa Python. Jalankan mode `AllUsers` dari PowerShell administrator di guest. Skrip menanam berkas dan backup uji, memeriksa hasil, lalu menjalankan uninstall di guest. [Skrip pengujian paket](../tests/windows_package.ps1)

```powershell
.\tests\windows_package.ps1 -PackageDir dist\fresh-v1.0.0 -Mode Portable
.\tests\windows_package.ps1 -PackageDir dist\fresh-v1.0.0 -BaselineSetup dist\WoofCleaner-Setup-0.1.0.exe -Mode CurrentUser
.\tests\windows_package.ps1 -PackageDir dist\fresh-v1.0.0 -BaselineSetup dist\WoofCleaner-Setup-0.1.0.exe -Mode AllUsers
```

Setiap judul B01–B14 merangkum satu batch. Tabel berikut menunjukkan urutan dan dependensinya.

| Target | Batch | Urutan dalam milestone |
|---|---|---|
| 0.1.1 | B01 sampai B03 | B01 dan B02 dapat dimulai langsung. B03 memakai hasil keduanya. |
| 0.2.0 | B04 sampai B06 | B04 mengambil baseline peluncuran. Lanjutkan B05 untuk layout dan interaksi, lalu B06 untuk respons saat scan. |
| 0.3.0 | B07 sampai B09 | B07 dan B08 bisa berjalan paralel. B09 memakai pencatatan hasil dari B08. |
| 0.4.0 | B10 sampai B12 | B10, B11, dan B12 bisa berjalan paralel. B10 memakai pilihan target dari B07. B12 membaca riwayat dari B08. |
| 1.0.0 | B13 dan B14 | B13 memeriksa paket kandidat, distribusi, dan update. B14 memakai paket yang sama untuk uji alur pengguna. |

### 0.1.1 | Pilihan jadwal dan pemulihan registry

Pada kode yang diwarisi dari seri lama, pemeriksaan `cmd_autoclean` dengan engine tiruan dan konteks admin menghasilkan 14 ID aturan untuk masing-masing kasus pengaturan belum ada, daftar kosong, dan satu ID kedaluwarsa. Daftar berisi satu ID kedaluwarsa dan `discord.cache` hanya memilih `discord.cache`. Pemeriksaan ini mengamati pilihan yang dikirim ke engine tanpa membersihkan PC.

#### B01. Hormati pilihan pengguna pada jadwal

- [x] Perbaiki pemilihan aturan di `cmd_autoclean` serta teks ringkasan jadwal. Pada baseline, pilihan kosong atau seluruh ID kedaluwarsa memicu fallback ke aturan default. Uji empat keadaan dengan engine tiruan: pengaturan belum pernah disimpan memakai default, daftar kosong menjalankan nol aturan, ID lama saja menjalankan nol aturan, dan daftar campuran hanya menjalankan ID yang masih valid. Pastikan filter admin tetap berlaku. [CLI](../woofcleaner/cli.py)

#### B02. Tulis backup sebelum mengubah registry

- [x] Simpan backup aturan `RegKey` secara persisten sebelum operasi penghapusan pertama yang dicakup backup. Pastikan proses yang gagal menulis backup meninggalkan registry utuh dan dua run berdekatan menghasilkan file terpisah. Uji pemulihan nilai termasuk data biner dan subtree lewat jalur Restore yang sudah ada. [Engine](../woofcleaner/engine.py) dan [restore](../woofcleaner/regscan.py)

#### B03. Uji jadwal dan restore lewat alur pengguna

- [x] Verifikasi kedua perbaikan melalui tes regresi dengan settings sementara dan key HKCU khusus pengujian. Kriteria rilisnya adalah hasil GUI, CLI, dan history jadwal cocok dengan pilihan pengguna, serta backup yang sudah tersimpan memulihkan objek uji.

### 0.2.0 | UI/UX desktop yang responsif

Di baseline 0.1.0, jendela dibuka pada 1240 × 780 dengan minimum 1020 × 640 dan sidebar tetap 240 piksel. Aplikasi membuat seluruh halaman sebelum menampilkan jendela. Pemindaian sudah memakai worker, tetapi antrean callback dan pengisian tabel hasil masih memakai thread Tk. Angka di bawah adalah target pengujian milestone. [Jendela dan navigasi](../woofcleaner/gui/app.py), [komponen bersama](../woofcleaner/gui/common.py), [hasil Custom Clean](../woofcleaner/gui/clean_tab.py)

#### B04. Ukur dan percepat peluncuran EXE

- [x] **Waktu buka.** Buat halaman berat saat pertama dikunjungi. Ukur dari peluncuran EXE sampai kontrol Analyze menerima input pada PC uji yang sama, masing-masing lima kali sebelum dan sesudah. Catat median dan pastikan pindah halaman lalu kembali mempertahankan centang pengguna.

#### B05. Benahi layout, hierarki visual, dan navigasi keyboard

- [x] **Layout dan DPI.** Sesuaikan ukuran awal dengan area kerja Windows. Buat sidebar bisa diringkas dan susun ulang toolbar serta kartu saat ruang menyempit. Pada laptop 1366 × 768 di skala 100% dan 150%, pengguna harus bisa mencapai Analyze, Run Cleaner, Stop, dan Settings. Periksa lagi setelah maximize dan restore.
- [x] **Hierarki visual.** Rapikan Custom Clean terlebih dahulu. Tampilkan Analyze sebagai langkah awal, bedakan status perkiraan dan hasil aktual, lalu tempatkan ringkasan ruang dan rincian item dalam urutan baca yang sama di kedua tema. Uji tampilan sebelum scan, saat hasil kosong, saat sebagian file terkunci, dan setelah Clean. Setiap keadaan harus menjelaskan tindakan yang tersedia. [Tema](../woofcleaner/gui/theme.py)
- [x] **Navigasi dan aksesibilitas.** Tambahkan fokus yang terlihat pada sidebar dan tindakan utama. Pengguna keyboard harus bisa berpindah halaman, mencentang aturan dengan Space, menjalankan Analyze, dan membatalkan dialog Clean dengan Esc lalu kembali ke pemicunya. Periksa teks biasa dengan target kontras 4,5:1 di tema terang dan gelap. Sertakan label teks untuk status gagal dan dilewati.

#### B06. Jaga interaksi saat scan dan pembatalan

- [x] **Respons saat scan.** Batasi pekerjaan per putaran antrean Tk dan isi tabel hasil secara bertahap. Dengan fixture 10.000 baris, ukur jeda event loop dan targetkan persentil ke-95 di bawah 150 ms. Selama scan, pengguna bisa menggulir, berpindah halaman, dan melihat status “Membatalkan” dalam 250 ms setelah menekan Stop.

### 0.3.0 | Hasil yang bisa diperiksa kembali

#### B07. Terapkan include dan exclude folder

- [x] Sediakan include/exclude folder dari GUI. Gunakan resolusi target yang sama untuk Analyze, Clean, dan jadwal. Uji fixture berisi subfolder yang dikecualikan dan junction. Keduanya harus tetap utuh setelah Clean.

#### B08. Satukan riwayat manual dan otomatis

- [x] Tambahkan riwayat pembersihan manual bersama riwayat otomatis yang sudah ada. Bedakan estimasi Analyze dari hasil eksekusi dan simpan status selesai, parsial, atau dibatalkan. Riwayat sejak baseline 0.1.0 dan data dari instalasi lama tetap terbaca. [Riwayat saat ini](../woofcleaner/scheduler.py)

#### B09. Ekspor hasil aktual ke CSV

- [x] Ekspor hasil Custom Clean dan Duplicate Finder ke CSV. Uji nama berkas Unicode dan koma, hasil kosong, dan pemindahan duplikat yang gagal sebagian. Setelah percobaan ulang, laporan harus mencerminkan hasil aktual setiap item.

### 0.4.0 | Health Check dan penggunaan ruang

#### B10. Gabungkan temuan dalam Health Check

- [x] Buat Health Check dari hasil engine dan inventaris startup. Scan awal hanya membaca. Pengguna dapat meninjau kategori, alasan skor, dan tindakan sebelum konfirmasi. Uji hasil kosong, browser terkunci, dan pembatalan.

#### B11. Tampilkan penggunaan disk dan filter duplikat

- [x] Buat ringkasan penggunaan ruang per jenis file serta filter duplikat tambahan. Untuk fixture yang sama, total kategori harus sama dengan total byte berkas yang berhasil dibaca. Tampilkan berkas yang dilewati.

#### B12. Hitung statistik dari riwayat

- [x] Tampilkan statistik dari riwayat 0.3.0. Pada contoh yang memuat scan, clean manual, dan clean terjadwal, jumlah ruang yang dibebaskan hanya menghitung hasil eksekusi.

### 1.0.0 | Distribusi stabil di Windows 11

Penerimaan B13–B14 untuk kandidat berasal dari konfirmasi pengguna. Validasi ulang paket final 1.0.0 di PC proyek mencakup suite otomatis, GUI dan CLI portable, versi installer serta SHA-256.

#### B13. Verifikasi paket Windows, upgrade, dan updater

- [x] Uji GUI dan CLI dari paket pada Windows 11 tanpa Python. Cek instalasi per-user, all-users, portable, dan upgrade dari baseline 0.1.0 dengan pilihan aturan, allowlist, serta backup lama.
- [x] Uji pembaruan dengan checksum benar, salah, dan hilang. Versi aplikasi, properti EXE, installer, tag, dan manifest checksum harus cocok dengan paket yang diuji.

#### B14. Uji siklus penggunaan sampai uninstall

- [x] Jalankan alur utama di mesin uji: Analyze, Clean atas fixture, jadwal, restore, lalu uninstall. Cocokkan isi fixture, ringkasan, tugas Windows, dan backup pengguna sesudah setiap tahap.

### Backlog tanpa target versi

Keputusan, perkiraan pekerjaan, dan skenario uji tiap fitur tersedia di [hasil riset R01–R05](FEASIBILITY.md). Tray dan bahasa diusulkan untuk 1.1. Fitur eksplorasi lainnya masih menunggu penetapan versi.

- [x] **R01. Tray dan bahasa.** Tentukan alur minimize, buka kembali, dan keluar dari tray. Inventarisasi teks UI yang perlu diterjemahkan dan uji satu halaman dengan label panjang pada skala 150%.
- [x] **R02. Diagnostik dan rollback driver.** Petakan gejala yang bisa dijelaskan wizard, data Windows yang tersedia, serta kondisi ketika driver sebelumnya dapat dipulihkan. Susun skenario uji pada perangkat uji dengan jalur pemulihan.
- [x] **R03. Penghapusan dan pemulihan berkas.** Bandingkan cakupan secure deletion, alternate data streams, wipe free space, dan file recovery menurut jenis volume. Tentukan cara mengukur hasil tiap fitur pada image disk uji.
- [x] **R04. Temporary uninstall dan sleep mode.** Untuk temporary uninstall, tentukan berkas, registry, dan masa simpan snapshot yang diperlukan untuk restore. Untuk sleep mode, tentukan cara menghentikan dan melanjutkan aplikasi serta cara menguji dampaknya pada proses lain.
- [x] **R05. Penyimpanan cloud dan informasi sistem.** Untuk Google Drive, OneDrive, dan Dropbox, petakan izin akun, estimasi ruang, dan opsi pemulihan. Untuk informasi sistem, tentukan data Windows yang bisa dibaca sebagai pengguna biasa dan buat contoh hasil.

Pembersihan password/kartu tersimpan serta perluasan registry ke kategori yang sengaja dilewati berada di luar cakupan proyek saat ini.

## Versioning dan rilis

| Versi | Bukti atau penggunaan |
|---|---|
| `0.1.0` (seri baru) | Baseline source dan build lokal. Nama tag yang dicadangkan untuk baseline adalah `fresh-v0.1.0`. |
| `0.4.0` (seri baru) | Kandidat lokal B01–B12 di `dist/fresh-v0.4.0/`. Kandidat ini menjadi dasar pengujian untuk 1.0.0. |
| `1.0.0` (seri baru) | Rilis stabil pertama. Installer Windows, GUI portable, CLI, dan manifest SHA-256 tersedia pada [rilis fresh-v1.0.0](https://github.com/Redwolfer/woof-cleaner/releases/tag/fresh-v1.0.0). |
| `v0.3.0` (arsip) | Tag Git `6897d68`. Cleaner, uninstaller, startup, Duplicate Finder, serta pembaruan software dan driver. |
| `v0.4.0` (arsip) | Tag Git `8827902`. Menambah Registry Cleaner, browser database cleaning, jadwal dan UI baru. EXE yang terpasang saat riset memakai seri lama `0.4.0`. Commit `26b664d` sesudah tag memperbaiki pengiriman catatan rilis. |

Gunakan `MAJOR.MINOR.PATCH` numerik. PATCH untuk koreksi perilaku yang sudah dijanjikan, MINOR untuk kemampuan baru yang kompatibel, dan MAJOR untuk perubahan kontrak yang memerlukan migrasi. Versi 1.0.0 menandai kontrak stabil pertama untuk CLI, ID aturan, settings, dan restore. Pembaruan dokumentasi saja dapat berada di antara rilis aplikasi. Rilis seri baru memakai tag `fresh-vX.Y.Z`. Updater memeriksa tag seri sebelum membandingkan angka versi. Tag historis `v0.3.0` dan `v0.4.0` tetap merujuk build lama. Untuk beralih dari instalasi lama, jalankan installer seri baru sekali, kemudian gunakan pembaruan dalam aplikasi. [Pembanding versi](../woofcleaner/selfupdate.py)

1. Saat siap merilis, ubah `__version__` di [woofcleaner/__init__.py](../woofcleaner/__init__.py). Build resmi membaca nilai ini untuk metadata kedua EXE dan parameter `AppVersion` installer.
2. Jalankan suite dan [build lokal](../build.ps1) dengan PyInstaller serta Inno Setup. Periksa `WoofCleaner-Setup-X.Y.Z.exe`, `WoofCleaner.exe`, dan `woof.exe` dari build itu. Selesaikan kriteria milestone, lalu commit perubahan.
3. Untuk publikasi, maintainer menjalankan `.\release.ps1 -Notes "..."` dari working tree bersih dengan tag baru. Skrip membangun ulang, membuat `SHA256SUMS.txt`, menyiapkan tag, mendorong HEAD dan tag ke origin, lalu mengunggah ketiga EXE dan checksum ke GitHub Releases. Opsi `-Draft` juga mendorong commit dan tag. [Skrip rilis](../release.ps1)
