# Riset CCleaner di PC proyek

Pemeriksaan 25 November 2026 menemukan bukti bahwa PC ini pernah menjalankan instalasi CCleaner 7.12.1526.1963. Log installer mencatat uninstall sukses pada 21 Oktober. Bukti lokal yang tersedia sekarang berupa log dan paket pembaruan lama. Perbandingan fitur di bawah menggunakan dokumentasi vendor karena sesi antarmuka aplikasi lokal tidak tersedia.

## Apa yang ditemukan di Windows

| Bukti | Hasil |
|---|---|
| Memori proyek Claude, `woof-cleaner-project.md` (20 Oktober 2026) | Menunjuk `C:\Program Files\Piriform\CCleaner 7` sebagai instalasi yang diteliti saat proyek dimulai. Catatan juga menjelaskan asal aturan Woof, pilihan winget/Windows Update, dan kebutuhan distribusi mandiri. |
| `%ProgramData%\Piriform\Icarus\Logs\icarus.log` | Baris 174 mencatat `piriform-ccl`, kanal `release`, dan versi produk lokal `7.12.1526.1963`. Log menyebut `CCleaner_service.exe` (1559) dan `ccleaner.ini` di direktori lama (2090). Baris 19256 mencatat operasi uninstall selesai dengan kode 0. |
| Inventaris saat pemeriksaan | Direktori instalasi lama sudah hilang. Pencarian entri Uninstall HKLM 64/32-bit dan HKCU, paket Appx pengguna, proses, layanan, dan shortcut Start Menu tidak menemukan CCleaner aktif. Windows masih mencatat Woof Cleaner 0.4.0. |
| `C:\Program Files\CCleaner\temp_ccupdate\ccupdate700_free.exe` | REA membaca paket PE32 berukuran 1.716.128 byte. Windows melaporkan deskripsi `CCleaner Self-Extract Package`, ProductVersion `7.0.984.1153`, FileVersion `25.7.9619.0`, dan tanda tangan valid dari Gen Digital Inc. SHA-256 `e3cd459f39a5a5b6110365ec243671e025921c62904e5250a8f988c8660ca452`. |

Untuk mengulang dua pemeriksaan utama secara baca-saja di PowerShell:

```powershell
$log = "$env:ProgramData\Piriform\Icarus\Logs\icarus.log"
Select-String -LiteralPath $log -Pattern "Local product version:", "Operation 'uninstall' finished" | Select-Object LineNumber, Line
$paket = "$env:ProgramFiles\CCleaner\temp_ccupdate\ccupdate700_free.exe"
(Get-Item -LiteralPath $paket).VersionInfo | Select-Object FileDescription, ProductVersion, FileVersion
Get-FileHash -LiteralPath $paket -Algorithm SHA256
```

## Perbandingan proses pengguna

Vendor menerbitkan v7.12.1526 pada 29 September 2026, sesuai tiga komponen pertama versi di log lokal. Vendor juga mendokumentasikan v7.14.1609 pada 18 November 2026. Tabel ini memakai perubahan lintas rilis sebagai pembanding desain. Edisi lisensi dan perilaku runtime pada instalasi lama belum terverifikasi. [Riwayat versi CCleaner](https://www.ccleaner.com/ccleaner/version-history)

| Proses di CCleaner menurut vendor | Woof 0.4.0 dan keputusan untuk proyek |
|---|---|
| Custom Clean memilih target, menganalisis, lalu membersihkan. Versi 7.12 menambah kategori cache aplikasi AI. [Catatan rilis](https://www.ccleaner.com/ccleaner/version-history) | Woof sudah punya enam aturan AI Tools. Nilai pekerjaan berikutnya ada pada konsistensi pilihan manual dan terjadwal serta pengecualian folder milik pengguna. |
| Health Check menggabungkan temuan data pelacakan browser, berkas sampah, dan aplikasi startup. [Panduan Health Check](https://support.ccleaner.com/s/article/using-health-check-in-ccleaner-7?language=en_US) | Pemindaian dan pengelolaan startup sudah bisa dilakukan terpisah. Milestone 0.4.0 pada seri baru menggabungkan hasil dan membawa pengguna ke tindakan yang dipilih. |
| Pengguna menjadwalkan perawatan. Catatan 7.05 dan 7.06 membahas pengecualian yang harus berlaku saat pekerjaan otomatis berjalan. [Pengaturan](https://support.ccleaner.com/s/article/configure-settings-in-ccleaner-7?language=en_US) dan [riwayat versi](https://www.ccleaner.com/ccleaner/version-history) | Woof menyimpan pilihan Custom Clean. Kasus nol pilihan dan ID kedaluwarsa perlu diuji sebelum menambah statistik atau jadwal baru. |
| Software Updater menampilkan aplikasi yang bisa diperbarui. Versi 7.14 juga memperbaiki pelaporan pembaruan gagal dan percobaan ulang pemindahan duplikat. [Software Updater](https://support.ccleaner.com/s/article/using-software-updater-in-ccleaner-7?language=en_US) dan [catatan rilis](https://www.ccleaner.com/ccleaner/version-history) | Woof sudah punya skip/ignore dan Duplicate Finder. Gunakan hasil parsial serta percobaan ulang sebagai kasus penerimaan pada ringkasan hasil. |
| Performance Optimizer menyediakan Sleep/Wake. Cloud Drive Cleaner bekerja dengan data akun cloud. [Riwayat versi](https://www.ccleaner.com/ccleaner/version-history) | Keduanya memerlukan model operasi baru di Woof, berupa pemantauan proses atau akses akun. Keduanya masuk daftar eksplorasi sesudah alur lokal stabil. |

Nama modul, nomor versi, dan status uninstall dapat ditelusuri ke log. Pengujian antarmuka, durasi scan, jumlah byte yang dibersihkan, dan kesetaraan hasil antarmesin membutuhkan pengamatan tersendiri. Pemetaan versi dan kriteria penerimaannya ada di [roadmap Woof](ROADMAP.md).
