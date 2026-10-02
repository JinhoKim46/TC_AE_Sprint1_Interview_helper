# Notes: Northwind Robotics (my own research)

- Founded 2018 in Gothenburg by two former warehouse-automation engineers. ~140 employees.
- Product: "Tern" autonomous mobile robots for pallets (Tern P1) and carts (Tern C2). About 900 robots at 35 sites; biggest customers are third-party logistics firms and an automotive parts supplier.
- Series B in early 2026 (around EUR 40M). Plans: US pilot sites and a new outdoor-capable model.
- Tech stack (from job ads and a meetup talk): Jetson Orin on the robot, ROS 2, C++ for the real-time stack, Python/PyTorch for training, an in-house labelling tool.
- Meetup talk by the Head of Perception: their biggest problems are rare objects (people carrying long items, fallen shrink-wrap) and reflective floors confusing the LiDAR.
- Culture: engineers visit customer sites regularly; blameless incident reviews.

## Questions I want to ask

- How is the release gate for a new perception model decided, and who can block it?
- How much of the 40 ms budget does detection get today?
- What does the data engine look like: how are hard examples found in fleet logs?
- How would my lack of LiDAR experience be handled in the first six months?
