# Auto Hardware Profile Design

## Muc tieu

Web tu nhan dien kha nang GPU cua may khach, chon cau hinh nhanh nhat van on
dinh, va tu fallback CPU khi GPU khong dung duoc. Nguoi dung van co the ep
`Auto`, `CPU`, hoac `GPU`.

## Phuong an

1. Chi kiem tra `nvidia-smi`: ngan nhung sai khi Docker khong truy cap GPU.
2. Browser dung WebGPU: khong cho biet Docker/CUDA/NVENC co dung duoc.
3. Host helper kiem GPU va chay smoke test Docker: chon phuong an nay.

Host helper da ton tai, chay localhost va chi chap nhan origin cua web tool.
Mo rong helper nho hon tao them service.

## Profile

- `cpu`: khong co GPU Docker hop le.
- `hybrid`: GPU hop le, VRAM duoi 6 GiB. Whisper va Ollama uu tien GPU theo
  tung giai doan; Demucs giu CPU; render dung NVENC neu smoke test dat.
- `gpu`: GPU hop le, VRAM tu 6 GiB. Whisper, Ollama, Demucs va render co the
  dung GPU.
- `auto`: host helper chon mot trong ba profile tren.

Neu nguoi dung ep `GPU` nhung smoke test that bai, job chay CPU va Doctor ghi
ro ly do fallback. Khong de job fail chi vi GPU.

## Luong du lieu

1. Web goi `GET http://127.0.0.1:18794/hardware`.
2. Host helper doc GPU host, VRAM, Docker va kha nang NVIDIA trong container.
3. Web gui ket qua da chon vao `PUT /api/settings`.
4. Backend luu `hardware_mode` va `hardware_profile` trong SQLite.
5. Job moi nhan bien moi truong profile.
6. Pipeline chon binary/backend GPU neu san sang; moi buoc tu fallback CPU.

## Docker

- `compose.yaml` giu CPU-safe mac dinh.
- `compose.gpu.yaml` chi them GPU reservation cho Ollama va tool.
- Host helper dung dung compose override GPU khi smoke test dat.
- Khong them API key, cookie, output command, hoac shell command tuy y.

## Web

Settings co select `Tu dong`, `Chi CPU`, `Uu tien GPU`.
Doctor hien:

- ten GPU va VRAM;
- profile da chon;
- Ollama, Whisper, Demucs, render dang dung CPU hay GPU;
- ly do fallback va nut `Nhan dien lai`.

## Kiem thu

- Unit test detector voi NVIDIA 4 GiB, NVIDIA 8 GiB, khong GPU, Docker GPU loi.
- Contract test host helper chi chay command co dinh.
- API/settings test allowlist `auto|cpu|gpu`.
- UI contract va browser test desktop/mobile.
- Docker smoke test xac nhan Ollama processor GPU khi profile GPU dat.
- E2E Bilibili bang URL `BV1ATDoYAENJ`, yeu cau `final_video_vi.mp4` hop le.

