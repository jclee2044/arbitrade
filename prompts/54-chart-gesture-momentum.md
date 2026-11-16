# More sensitive chart zoom with momentum

User request:

> it can be a little more sensitive. also if you zoom and release quickly, it should continue moving and slow down like this curve. same with scrolling in the chart

The attached sketch shows a steep initial motion that decays gradually to a flat tail. Increase the existing horizontal zoom sensitivity modestly and implement smooth release momentum for trackpad zoom and chart scrolling, preserving history navigation and existing work. Verify continued movement, deceleration, stopping and cancellation in the browser. No dependencies or commits without the required review.
