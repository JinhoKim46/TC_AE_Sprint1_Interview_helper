# Machine Learning Engineer, Perception

**Northwind Robotics** · Gothenburg, Sweden (hybrid, 3 days on site) · Full-time

## About us

Northwind Robotics builds autonomous mobile robots (AMRs) that move pallets and carts inside
warehouses and factories. Our robots work next to people, so perception has to be fast, reliable
and safe. We have 140 people, about 900 robots running at 35 customer sites in Europe, and we
closed a Series B round in early 2026.

## The team

The Perception team (9 engineers) owns everything between the sensors and the planner: object
detection, segmentation, tracking and free-space estimation from cameras and 2D/3D LiDAR. Models
run on an NVIDIA Jetson Orin on each robot, with a hard budget of 40 ms per frame for the full
perception stack.

## What you will do

- Train, evaluate and ship detection and segmentation models for people, forklifts, pallets and
  floor hazards (spills, debris).
- Optimise models for on-robot inference (quantisation, pruning, TensorRT) and keep them inside
  the latency budget.
- Build and improve our data engine: mining hard examples from fleet logs, labelling workflows,
  and dataset versioning.
- Design offline and on-robot evaluation, including safety metrics such as person recall at
  distance, and own the release gate for new models.
- Work with the Planning and Safety teams to define what "good enough" means for a release.
- Investigate field incidents: reproduce a failure from logs, find the root cause, and fix it.

## Requirements (must have)

1. 3+ years of experience training and shipping deep learning models for computer vision
   (detection, segmentation or tracking) to production.
2. Strong Python and PyTorch; you write tested, reviewed code.
3. Experience deploying models under tight latency or memory constraints (edge devices, mobile,
   or embedded), including quantisation or TensorRT/ONNX optimisation.
4. Solid understanding of evaluation: choosing metrics, building test sets that reflect the real
   world, and spotting dataset bias or leakage.
5. Working knowledge of C++ (reading and modifying inference code that runs on the robot).
6. Clear communication with non-ML engineers, for example explaining a model's failure modes to
   the Safety team.

## Nice to have

7. Experience with 3D perception or sensor fusion (LiDAR point clouds, camera-LiDAR
   calibration).
8. ROS 2 experience.
9. Experience building a data engine / active learning loop at scale.
10. Background in safety-critical systems (ISO 13849, ISO 3691-4 or similar).

## What we offer

- Salary 62,000-75,000 SEK per month depending on experience, plus employee stock options.
- 30 days of vacation, a learning budget of 15,000 SEK per year, and conference travel.
- Time on site with real robots: every engineer spends at least one day a quarter at a customer
  site.

## Interview process

1. Recruiter screen (30 min)
2. Hiring manager interview (45 min): past projects and motivation
3. Technical deep dive (60 min): ML fundamentals, a past project in depth, deployment trade-offs
4. Take-home or live case: design a perception evaluation for a new robot model
5. Final round with the team and the Head of Engineering
