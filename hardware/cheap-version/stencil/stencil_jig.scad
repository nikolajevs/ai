// Parametric paste-printing jig for cheap-version (100 x 100 mm PCB).
//
// Export separate parts with OpenSCAD:
//   openscad -D 'part="base"'  -o stencil_jig_base.stl  stencil_jig.scad
//   openscad -D 'part="frame"' -o stencil_jig_frame.stl stencil_jig.scad
//
// The stencil is 130.05 x 130.05 mm: 15 mm of blank field on every side of
// the 100.05 mm board.  The lower tray has a 0.2 mm recessed stencil shelf,
// so a 0.2 mm stencil and the bare PCB finish at the same height.

$fn = 48;

part = is_undef(part) ? "assembly" : part;

pcb_w = 100.05;
pcb_h = 100.05;
pcb_t = 1.60;
pcb_clearance = 0.30;       // clearance on each side of the PCB pocket

stencil_margin_x = 15.0;    // left/right blank field
stencil_margin_y = 15.0;    // front/back blank field; set to 0 for side-only fields
stencil_t = 0.20;
stencil_clearance = 0.30;   // clearance on each side of the stencil pocket

base_t = 5.0;
stencil_recess = 0.20;
base_border = 8.0;
base_corner_r = 3.0;

frame_border = 3.0;
frame_t = 3.2;
frame_corner_r = 2.0;
frame_gap = 0.05;            // small compression of the stencil/soft strip

hinge_pin_d = 3.0;           // use a smooth M3 screw or 3 mm rod as the pin
hinge_hole_d = 3.5;
hinge_od = 7.0;
hinge_y = (pcb_h + 2 * (stencil_margin_y + base_border)) / 2 + 1.5;
// The pin axis is one tube radius above the bottom plane of the frame, so the frame prints flat on its bottom face with
// the knuckle tube resting on the same plane: no support, nothing hangs in the air.
hinge_z = (base_t - stencil_recess) + stencil_t - frame_gap + hinge_od / 2;
hinge_span = 110.0;
hinge_axial_gap = 1.0;
// The frame ear ends this far behind the axis.  Its lower corner must stay inside the circle that the base plate edge
// leaves free (the edge is 3.77 mm from the axis): sqrt(3.5^2 + 0.8^2) = 3.59 mm, so the frame opens past 170 degrees
// without touching the base.
hinge_frame_reach = 0.8;
hinge_knuckle_len = (hinge_span - 2 * hinge_axial_gap) / 3;
hinge_base_x_left = -hinge_span / 2;
hinge_frame_x = -hinge_knuckle_len / 2;
hinge_base_x_right = hinge_frame_x + hinge_knuckle_len + hinge_axial_gap;
// Along the pin: base 36 mm, 1 mm gap, frame 36 mm, 1 mm gap, base 36 mm.

latch_hole_d = 3.5;
latch_nut_af = 6.4;          // M3 hex nut pocket, measured across corners here
latch_y = -(pcb_h + 2 * (stencil_margin_y + frame_border)) / 2 - 1.5;

// BT301 is on the bottom of the board.  These values are deliberately easy to
// change if the holder position or a future board revision changes.
battery_relief_x = 27.9;     // board-centred coordinates, from cheap-version PCB
battery_relief_y = 2.0;
battery_relief_w = 32.0;
battery_relief_h = 28.0;

stencil_w = pcb_w + 2 * stencil_margin_x;
stencil_h = pcb_h + 2 * stencil_margin_y;
base_w = stencil_w + 2 * base_border;
base_h = stencil_h + 2 * base_border;
frame_inner_w = pcb_w + 1.0;
frame_inner_h = pcb_h + 1.0;
frame_outer_w = stencil_w + 2 * frame_border;
frame_outer_h = stencil_h + 2 * frame_border;

stencil_shelf_z = base_t - stencil_recess;
pcb_floor_z = stencil_shelf_z - pcb_t;
frame_z = stencil_shelf_z + stencil_t - frame_gap;

module rounded_prism(w, d, h, r) {
    if (r <= 0) {
        cube([w, d, h]);
    } else {
        linear_extrude(height = h)
            hull() {
                for (x = [-w / 2 + r, w / 2 - r])
                    for (y = [-d / 2 + r, d / 2 - r])
                        translate([x, y]) circle(r = r);
            }
    }
}
module ring(outer_w, outer_h, inner_w, inner_h, z, h, r) {
    translate([0, 0, z])
        difference() {
            rounded_prism(outer_w, outer_h, h, r);
            translate([0, 0, -0.1])
                rounded_prism(inner_w, inner_h, h + 0.2, max(0.8, r - 1.0));
        }
}

// A hinge ear is a block from the plate edge to the knuckle tube, exactly as wide as the knuckle (x0 is where the knuckle
// starts along the pin).  The base ear rises to the axis and reaches the far side of the tube; the frame ear is as thick
// as the frame and ends hinge_frame_reach behind the axis.  Both parts print flat without support: the lower half of every
// tube sits on its ear.  The pin bore is cut from the joined solid (see base() and frame()), so the ear cannot fill it,
// and it is a teardrop with the point up, so the top of the horizontal hole is not a bridge.
module hinge_tube(x0, len) {
    translate([x0, hinge_y, hinge_z])
        rotate([0, 90, 0])
            cylinder(h = len, d = hinge_od);
}

module hinge_bore(x0, len) {
    // teardrop: the point of the bore faces up (local -x becomes global +z after the rotation)
    translate([x0 - 0.1, hinge_y, hinge_z])
        rotate([0, 90, 0])
            linear_extrude(height = len + 0.2)
                hull() {
                    circle(d = hinge_hole_d);
                    translate([-hinge_hole_d / 2 * sqrt(2), 0]) square(0.01, center = true);
                }
}

module base_hinge_arm(x0, len) {
    y0 = base_h / 2 - 0.5;
    translate([x0, y0, 0])
        cube([len, hinge_y + hinge_od / 2 - y0, hinge_z]);
}

module frame_hinge_arm(x0, len) {
    y0 = frame_outer_h / 2 - 0.5;
    translate([x0, y0, frame_z])
        cube([len, hinge_y + hinge_frame_reach - y0, frame_t]);
}

module latch_hole(x, z0, h) {
    translate([x, latch_y, z0])
        cylinder(h = h, d = latch_hole_d);
}

module base() {
    difference() {
        union() {
            difference() {
                rounded_prism(base_w, base_h, base_t, base_corner_r);

                // The stencil pocket registers its outside edge.  Its floor and the
                // PCB pocket are coplanar, so the stencil sits directly on the PCB.
                translate([0, 0, stencil_shelf_z])
                    rounded_prism(stencil_w + 2 * stencil_clearance,
                                  stencil_h + 2 * stencil_clearance,
                                  base_t - stencil_shelf_z + 0.2, 2.0);
                translate([0, 0, pcb_floor_z])
                    rounded_prism(pcb_w + 2 * pcb_clearance,
                                  pcb_h + 2 * pcb_clearance,
                                  stencil_shelf_z - pcb_floor_z + 0.2, 0.8);

                // Relief for the bottom CR2032 holder.  The rest of the PCB is
                // supported by the pocket floor; no mounting holes are required.
                translate([battery_relief_x, battery_relief_y, -0.1])
                    rounded_prism(battery_relief_w, battery_relief_h,
                                  pcb_floor_z + 0.3, 2.0);

                // Captive M3 nut pockets under the two front latch screws.
                for (x = [-52, 52]) {
                    latch_hole(x, -0.1, base_t + 0.2);
                    translate([x, latch_y, -0.1])
                        cylinder(h = 2.6, r = latch_nut_af / 2, $fn = 6);
                }
            }

            // Two base ears with their knuckles; the frame knuckle goes between them.
            for (x0 = [hinge_base_x_left, hinge_base_x_right]) {
                base_hinge_arm(x0, hinge_knuckle_len);
                hinge_tube(x0, hinge_knuckle_len);
            }
        }

        for (x0 = [hinge_base_x_left, hinge_base_x_right])
            hinge_bore(x0, hinge_knuckle_len);
    }
}

module frame() {
    difference() {
        union() {
            ring(frame_outer_w, frame_outer_h,
                 frame_inner_w, frame_inner_h,
                 frame_z, frame_t, frame_corner_r);

            // Front tabs sit over the captive nuts in the base.
            for (x = [-52, 52])
                translate([x, latch_y, frame_z])
                    rounded_prism(10, 10, frame_t, 1.2);

            // One ear in the middle of the back edge, with the frame knuckle
            // interleaved between the two base knuckles.
            frame_hinge_arm(hinge_frame_x, hinge_knuckle_len);
            hinge_tube(hinge_frame_x, hinge_knuckle_len);
        }

        for (x = [-52, 52])
            latch_hole(x, frame_z - 0.1, frame_t + 0.2);

        hinge_bore(hinge_frame_x, hinge_knuckle_len);
    }
}

// Short hinge sample for a quick test print: the same ears, tubes, bores and gaps as the jig, three 12 mm knuckles and
// small plate stubs at the same heights.  Print "hinge_test_base" and "hinge_test_frame" flat, without support, push a
// 3 mm pin through and check the fit and the swing before printing the whole jig.
test_len = 12.0;
test_stub_w = 3 * test_len + 2 * hinge_axial_gap;
test_x_base_left = -test_stub_w / 2;
test_x_frame = -test_len / 2;
test_x_base_right = test_x_frame + test_len + hinge_axial_gap;

module hinge_test_base() {
    difference() {
        union() {
            translate([test_x_base_left, base_h / 2 - 10, 0])
                cube([test_stub_w, 10, base_t]);
            for (x0 = [test_x_base_left, test_x_base_right]) {
                base_hinge_arm(x0, test_len);
                hinge_tube(x0, test_len);
            }
        }
        for (x0 = [test_x_base_left, test_x_base_right])
            hinge_bore(x0, test_len);
    }
}

module hinge_test_frame() {
    difference() {
        union() {
            translate([test_x_base_left, frame_outer_h / 2 - 10, frame_z])
                cube([test_stub_w, 10, frame_t]);
            frame_hinge_arm(test_x_frame, test_len);
            hinge_tube(test_x_frame, test_len);
        }
        hinge_bore(test_x_frame, test_len);
    }
}

if (part == "base") {
    base();
} else if (part == "frame") {
    frame();
} else if (part == "hinge_test_base") {
    hinge_test_base();
} else if (part == "hinge_test_frame") {
    hinge_test_frame();
} else {
    // Closed assembly preview.  The two parts are intentionally coplanar;
    // export the separate parts for printing.
    base();
    frame();
}
