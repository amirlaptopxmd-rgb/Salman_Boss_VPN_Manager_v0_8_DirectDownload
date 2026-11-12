SALMAN BOSS VPN MANAGER v0.5 — IN-APP DIRECT DOWNLOAD

নতুন পরিবর্তন:
- Download Center-এ চারটি আলাদা Download বাটন।
- বাটনে ক্লিক করলে installer অ্যাপের ভিতরের downloader দিয়ে ডাউনলোড হবে।
- Progress bar, ডাউনলোডের অবস্থা এবং Cancel।
- ডাউনলোডের ফাইল যাবে: Downloads\\SalmanBossVPN
- ডাউনলোড শেষ হলে installer চালু করার অনুমতি চাইবে।
- Proton VPN-এর সর্বশেষ Windows EXE অফিসিয়াল ProtonVPN GitHub Releases API থেকে খুঁজে নেয়।
- অন্য VPN ইনস্টল করার পর Browse করে তার .exe Add করা যাবে।

সতর্কতা:
- ইনস্টলার চালু করলে Windows UAC/admin অনুমতি চাইতে পারে; ব্যবহারকারীকে নিজে অনুমোদন করতে হবে।
- ExpressVPN account activation এবং vendor-specific setup প্রয়োজন হতে পারে।
- PIA installer URL সংস্করণভিত্তিক; ভবিষ্যতে vendor URL বদলালে ডাউনলোড ব্যর্থ হতে পারে।
- এই সংস্করণে Pause/Resume নেই; Cancel আছে।
- কেবল vendor-এর official domain থেকে আসা download redirect গ্রহণ করা হয়।
- এই পরিবেশে Windows runtime/installer পরীক্ষা সম্ভব হয়নি; Python syntax validation করা হয়েছে।

চালানো:
1) Python 3.11+ ইনস্টল করুন।
2) pip install -r requirements_DownloadCenter.txt
3) python Salman_Boss_VPN_Manager_v0_5_DirectDownload.py
EXE বানাতে BUILD_EXE_DirectDownload.bat চালান।
