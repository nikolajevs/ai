#!/usr/bin/env python3
"""Regress topology/current conservation in the ampacity screening model.

Run with the KiCad Python interpreter. No repository PCB is changed.
"""
import unittest

import pcbnew as p

from ampacity import analyze_net


def point(x, y):
    return p.VECTOR2I(p.FromMM(x), p.FromMM(y))


def fixture(reverse=False, mirror=False, connected=True, floating=False):
    board = p.BOARD()
    board.SetCopperLayerCount(4)
    net = p.NETINFO_ITEM(board, 'POWER')
    board.Add(net)
    pads = {}
    for ref, x, layer in [('SRC', 0, p.F_Cu), ('DST', 20, p.B_Cu)]:
        fp = p.FOOTPRINT(board)
        fp.SetReference(ref)
        board.Add(fp)
        pad = p.PAD(fp)
        pad.SetNumber('1')
        pad.SetAttribute(p.PAD_ATTRIB_SMD)
        pad.SetShape(p.PAD_SHAPE_RECT)
        pad.SetSize(point(2, 3))
        layers = p.LSET()
        layers.AddLayer(layer)
        pad.SetLayerSet(layers)
        pad.SetNet(net)
        fp.Add(pad)
        pad.SetPosition(point(x, 0))
        pads[ref + '.1'] = pad
    # Both 3-mm-wide faces overlap a 2 x 2 bank. The two vias in each
    # transverse row have exactly the same projection onto both track axes.
    tracks = [p.F_Cu, p.B_Cu]
    if reverse:
        tracks.reverse()
    for layer in tracks:
        track = p.PCB_TRACK(board)
        track.SetStart(point(0, 0))
        track.SetEnd(point(20, 0))
        track.SetWidth(p.FromMM(3))
        track.SetLayer(layer)
        track.SetNet(net)
        board.Add(track)
    locations = [(6, -.6), (6, .6), (14, -.6), (14, .6)] if connected else []
    if floating:
        locations.append((100, 100))
    if reverse:
        locations.reverse()
    for x, y in locations:
        via = p.PCB_VIA(board)
        via.SetPosition(point(x, -y if mirror else y))
        via.SetWidth(p.FromMM(1))
        via.SetDrill(p.FromMM(.5))
        via.SetViaType(p.VIATYPE_THROUGH)
        via.SetLayerPair(p.F_Cu, p.B_Cu)
        via.SetNet(net)
        board.Add(via)
    return board, pads


def run_fixture(**kwargs):
    board, pads = fixture(**kwargs)
    return analyze_net(board, pads, 'POWER', 'SRC.1', {'DST.1': 4}, 35, 17.5)


class AmpacityTopologyTests(unittest.TestCase):
    def currents(self, result, unmirror=False):
        return {(v['at_mm'][0], -v['at_mm'][1] if unmirror else v['at_mm'][1]): v['i_a']
                for v in result['via_currents']}

    def test_all_transverse_vias_share_current(self):
        result = run_fixture()
        self.assertNotIn('error', result)
        currents = self.currents(result)
        self.assertEqual(len(currents), 4)
        for x in [6, 14]:
            self.assertGreater(currents[x, -.6], .1)
            self.assertGreater(currents[x, .6], .1)
            self.assertAlmostEqual(currents[x, -.6], currents[x, .6], places=3)
        self.assertAlmostEqual(sum(currents.values()), 4, places=3)
        self.assertLess(result['max_kcl_residual_a'], 4e-6)

    def test_contact_insertion_order_does_not_change_result(self):
        ordinary, reversed_order = run_fixture(), run_fixture(reverse=True)
        self.assertEqual(self.currents(ordinary), self.currents(reversed_order))
        self.assertEqual(ordinary['drop_mv'], reversed_order['drop_mv'])

    def test_reflection_does_not_change_result(self):
        ordinary, reflected = run_fixture(), run_fixture(mirror=True)
        self.assertEqual(self.currents(ordinary), self.currents(reflected, unmirror=True))
        self.assertEqual(ordinary['drop_mv'], reflected['drop_mv'])

    def test_disconnected_sink_is_rejected(self):
        result = run_fixture(connected=False)
        self.assertIn('disconnected source/sink', result['error'])

    def test_floating_uninjected_via_is_excluded(self):
        ordinary, floating = run_fixture(), run_fixture(floating=True)
        self.assertNotIn('error', floating)
        self.assertEqual(self.currents(ordinary), self.currents(floating))
        self.assertEqual(floating['floating_model_nodes_excluded'], 4)

    def test_resistance_sensitivity_preserves_current_conservation(self):
        for scale in [.5, 1, 2]:
            with self.subTest(scale=scale):
                board, pads = fixture()
                result = analyze_net(board, pads, 'POWER', 'SRC.1', {'DST.1': 4}, 35, 17.5, scale)
                self.assertNotIn('error', result)
                self.assertLess(result['max_kcl_residual_a'], 4e-6)
                self.assertAlmostEqual(sum(self.currents(result).values()), 4, places=3)


if __name__ == '__main__':
    unittest.main()
