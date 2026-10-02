# Cover letter — Machine Learning Engineer, Perception

Dear Northwind Robotics hiring team,

I am applying for the Machine Learning Engineer, Perception role. For four years I have trained
vision models that leave the notebook and meet the real world, and I want the next step to be the
hardest version of that: models that run on a moving robot, next to people, inside a 40 ms
budget.

**Making a model fit where it has to run.** At Fieldsight, our disease classifier only worked
online, but farmers often have no signal in the field. I took on moving it onto the phone. The
first int8 version lost 4 accuracy points because a few layers were very sensitive to
quantisation. I found them with a per-layer sensitivity check, kept those in float16, and added
quantisation-aware fine-tuning. The final model was four times smaller and almost four times
faster, with less than one point of accuracy lost. Offline use of the app went from zero to 41%
of all scans within two months.

**Trusting the numbers.** At Shelfwise, customers complained about missed products while our
dashboard said 0.89 mAP. I dug into the test set and found that a third of it came from stores
that were also in training. When I rebuilt the split by store, the score dropped six points.
Presenting a worse number to leadership was uncomfortable, but it changed how we evaluated
everything afterwards, and the next two model releases improved what customers actually saw. I
think about your "person recall at distance" metric in the same way: the metric must match the
risk.

**Learning a new domain fast.** Last year I built a small pallet detector for a Raspberry Pi
robot in my spare time, because I wanted to understand robotics beyond reading about it. It was
humbling: motion blur, bad lighting and a camera mounted 20 cm off the floor broke assumptions I
had from drone and shelf images.

I will be honest about the gaps. My C++ is at the level of reading and small changes, and I have
not yet worked with LiDAR or ROS 2. I learn quickly when the work is real, and I would welcome
the chance to spend time on site with your robots.

Thank you for considering my application.

Kind regards,
Maya Lindqvist
