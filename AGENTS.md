# Woof Cleaner | README untuk LLM

Woof Cleaner membantu pengguna Windows melihat data yang bisa dibersihkan, memilih tindakan, lalu memeriksa hasilnya. GUI Tkinter, CLI, dan jadwal memakai modul Python yang sama. Seri baru dimulai dari 0.1.0 pada 25 November 2026 dan membawa fitur yang sudah tersedia. Untuk memilih pekerjaan berikutnya, buka [milestone dan TODO](docs/ROADMAP.md). Untuk membandingkan perilaku dengan CCleaner, gunakan [hasil riset PC ini](docs/CCLEANER_RESEARCH.md).

## Proses bisnis

| Kebutuhan pengguna | Alur dan hasil | Titik masuk di kode |
|---|---|---|
| Membebaskan ruang atau menghapus jejak browser | Custom Clean memuat aturan, mendeteksi aplikasi, dan menampilkan pilihan. Analyze menghitung kandidat. Run Cleaner meminta konfirmasi, memeriksa ulang target saat eksekusi, lalu menampilkan berkas, byte, record, entri registry, dan item yang terkunci. GUI mengizinkan langsung Run Cleaner. CLI `clean` selalu menganalisis dahulu. | [Tab pembersihan](woofcleaner/gui/clean_tab.py), [CLI](woofcleaner/cli.py), [engine](woofcleaner/engine.py), [SQLite browser](woofcleaner/browserdb.py) |
| Mengulang pembersihan | Pengguna menyimpan centang di Custom Clean dan membuat jadwal. Task Scheduler menjalankan jadwal kalender, sedangkan entri Run pengguna menangani sign-in. Keduanya memanggil `auto-clean` tanpa dialog. Proses biasa menyaring aturan admin. Hasil masuk ke 100 entri terakhir `autoclean_history`. Pilihan kosong atau seluruh ID kedaluwarsa menjalankan nol aturan. | [Jadwal](woofcleaner/scheduler.py), `cmd_autoclean` di CLI |
| Memulihkan atau mengendalikan konfigurasi Windows | Registry memindai referensi lokal yang hilang. Pengguna memilih temuan, menjalankan Fix dan bisa memulihkan backup JSON. Startup Manager mencakup aplikasi startup, layanan, dan menu konteks. Dampak dan kebutuhan admin bergantung pada tindakan. | [Registry](woofcleaner/regscan.py), [startup](woofcleaner/startup.py), [layanan](woofcleaner/services.py), [menu konteks](woofcleaner/contextmenu.py) |
| Menghapus aplikasi atau duplikat | Uninstaller menjalankan uninstaller vendor dan menawarkan pemeriksaan sisa. Duplicate Finder mengelompokkan berkas menurut ukuran lalu hash isi. Pengguna memilih salinan dan menyisakan setidaknya satu per grup. Folder sisa dan duplikat terpilih masuk Recycle Bin. | [Uninstaller](woofcleaner/uninstaller.py), [duplikat](woofcleaner/duplicates.py) |
| Memperbarui perangkat lunak | Pengguna melihat kandidat, memasang pembaruan, melewati satu versi atau mengabaikan aplikasi/perangkat. Aplikasi menggunakan winget dan driver menggunakan Windows Update. Pembaruan Woof sendiri mengambil aset GitHub Releases dan memverifikasi SHA-256. | [Software Updater](woofcleaner/updater.py), [Driver Updater](woofcleaner/drivers.py), [pembaruan Woof](woofcleaner/selfupdate.py) |

## Kontrak yang perlu dijaga

- Tulis aturan orisinal di [data/rules.ini](data/rules.ini). Parser membaca subset format INI yang didokumentasikan proyek. Versi 0.1.0 memuat 75 ID unik, 14 aktif secara default. Pertahankan ID karena pengaturan, jadwal, dan CLI menyimpan atau menerima ID tersebut. [Parser](woofcleaner/rules.py)
- Analyze harus mempertahankan isi target. Custom Clean menghapus berkas secara permanen saat Clean. Pertahankan pemeriksaan root dan reparse point, filter umur, pengecualian, serta penanganan berkas terkunci. Saat menyentuh SQLite, uji bookmark Firefox, allowlist cookie termasuk subdomain, dan database terkunci. [Tes engine](tests/test_engine.py) dan [tes fitur](tests/test_features.py)
- Bedakan dua jalur registry. Tombol Fix memakai `regscan.fix` yang menulis backup ke disk sebelum mengubah registry. Aturan `RegKey` milik Custom Clean 0.1.0 menyimpan salinan di memori dan baru menulis JSON setelah loop selesai. Sejak perbaikan B02, engine menyimpan snapshot ke disk dahulu, kemudian memeriksa ulang target sebelum menghapusnya. [Engine](woofcleaner/engine.py)
- Saat berjalan dari source, `settings.json` dan `backups/` berada di root repo. EXE memakai `%LOCALAPPDATA%\WoofCleaner`. Pada build EXE, `rules.ini` di samping EXE menggantikan aturan bawaan. Untuk data runtime baru, pasangkan resolusi path di [paths.py](woofcleaner/paths.py) dengan `--add-data` di [build.ps1](build.ps1).
- Target distribusi proyek adalah Windows 11 tanpa instalasi Python pengguna. Pertahankan stdlib untuk runtime, dua entry point GUI/CLI, dan AppId Inno Setup agar versi baru mengenali instalasi lama. Catatan proyek Claude menjadi referensi untuk keputusan ini. [Installer](installer/woofcleaner.iss)

## Mulai bekerja dari root repo

```powershell
python -m woofcleaner --help
python -m woofcleaner list
python -m unittest discover -s tests -v
```

Kandidat lokal seri baru saat ini adalah 0.4.0. Build menempatkan artefak di `dist/fresh-v<versi>/`. PC overview memakai [laporan](woofcleaner/reports.py) untuk penggunaan disk dan statistik.

Untuk GUI gunakan `python -m woofcleaner`. Untuk uji perubahan pembersihan, arahkan aturan ke direktori sementara atau database fixture. Cocokkan hasil melalui entry point yang terdampak, termasuk jadwal jika mengubah pemilihan aturan. Perintah build lokal adalah `.\build.ps1`. Proses publikasi dan sumber nomor versi ada di [roadmap](docs/ROADMAP.md#versioning-dan-rilis).
