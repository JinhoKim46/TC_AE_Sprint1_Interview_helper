# Maya Lindqvist

Machine Learning Engineer · Malmö, Sweden · maya.lindqvist@example.com · github.com/example-maya

## Summary

Machine learning engineer with 4.5 years of experience in computer vision, mostly detection and
segmentation for retail and agriculture. I have shipped models to mobile phones and to cloud
APIs, and I like owning a model from data collection to monitoring in production.

## Experience

### Senior Machine Learning Engineer — Fieldsight AgriTech, Malmö
*Mar 2024 – present*

Fieldsight sells drones and a phone app that help farmers spot crop disease and weeds.

- Lead engineer for weed segmentation (U-Net, then SegFormer-B1) on drone images; raised mIoU
  from 0.61 to 0.74 on our field test set while keeping inference under 0.8 s per image on the
  cloud GPU.
- Built a hard-example mining pipeline: the model flags low-confidence tiles, agronomists label
  them in Label Studio; 6 labelling rounds cut false positives on young crops by 38%.
- Moved the disease classifier (EfficientNet-B0) onto Android phones with TFLite int8
  quantisation: model size 21 MB → 5.4 MB, latency 180 ms → 48 ms on a mid-range phone, accuracy
  drop 0.9 points.
- Set up dataset versioning (DVC) and a model card for each release; mentor 2 junior engineers.

### Machine Learning Engineer — Shelfwise, Copenhagen
*Jun 2021 – Feb 2024*

Shelfwise analyses photos of supermarket shelves to find empty spots and wrong prices.

- Trained YOLOv5 / YOLOv8 product detectors for 4,000+ SKUs; mAP@0.5 from 0.71 to 0.83 through
  better labelling guidelines, mosaic augmentation and class-balanced sampling.
- Discovered that our test set leaked: 30% of test images came from stores also in training.
  Rebuilt the split by store; reported mAP dropped 6 points, but it finally matched what
  customers saw.
- Served models with TorchServe on AWS (p95 latency 210 ms, about 1.2M images per month).
- Wrote the monthly model-quality report for the account managers and joined customer calls to
  explain errors.

### Data Scientist (intern, then junior) — Kattegat Insurance, Gothenburg
*Sep 2019 – May 2021*

- Built a damage-photo classifier (ResNet-50) that routed 25% of car claims to fast-track
  handling.
- Python, pandas, scikit-learn; first experience with PyTorch and Docker.

## Projects

- **Pallet detection on a hobby robot (2025):** Raspberry Pi 5 + camera; trained a small
  YOLOv8n and ran it with ONNX Runtime at 9 FPS. Blog post: "What I learned putting a detector
  on a robot vacuum".
- **Open-source contribution:** fixed a bug in the mask export of an open-source labelling tool
  (merged PR, 2023).

## Skills

- **ML:** PyTorch, torchvision, Ultralytics YOLO, SegFormer, TFLite, ONNX Runtime, basic TensorRT
  (one tutorial project), Weights & Biases, DVC
- **Languages:** Python (daily), SQL, some C++ (university courses, reading code)
- **Infrastructure:** Docker, AWS (S3, SageMaker, ECS), GitHub Actions, Label Studio
- **Languages spoken:** Swedish (native), English (fluent), Danish (good)

## Education

M.Sc. Computer Science (Machine Learning), Lund Institute of Technology, 2019 — thesis: "Few-shot
segmentation of satellite images".
