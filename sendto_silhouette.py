#!/usr/bin/env python 
#
# Inkscape extension for driving a silhouette cameo
# (C) 2013 jw@suse.de. Licensed under CC-BY-SA-3.0 or GPL-2.0 at your choice.
#
# code snippets visited to learn the extension 'effect' interface:
# - http://sourceforge.net/projects/inkcut/
# - http://code.google.com/p/inkscape2tikz/
# - http://wiki.inkscape.org/wiki/index.php/PythonEffectTutorial
# - http://github.com/jnweiger/inkscape-gears-dev
# - http://code.google.com/p/eggbotcode/
# - http://www.bobcookdev.com/inkscape/better_dxf_output.zip
#
# 2013-05-09 jw, V0.1 -- initial draught
# 2013-05-10 jw, V0.2 -- can plot simple cases without transforms.
# 2013-05-11 jw, V0.3 -- still using inkcut/plot.py -- fixed write(), 
#                        improved logging, flipped y-axis.
# 2013-05-12 jw, v0.4 -- No unintended multipass when nothing is selected. 
#                        Explicit multipass option added.
#                        Emplying recursivelyTraverseSvg() from eggbotcode
#                        TODO: coordinate system of page is not exact.
# 2013-05-13 jw, v0.5 -- transporting docWidth/docHeight to dev.page()
# 2013-05-15 jw, v0.6 -- Replaced recursivelyTraverseSvg() and friends with the
#                        versions from eggbot.py, those from eggbot_hatch.py
#                        would only do closed paths. Makes sense for them, but
#                        not for us. 

import sys, os, shutil, time, logging
sys.path.append('/usr/share/inkscape/extensions')

# We will use the inkex module with the predefined Effect base class.
import inkex
from bezmisc import *
from simpletransform import *
import simplepath
import cubicsuperpath
import cspsubdiv

from silhouette.Graphtec import SilhouetteCameo
## from silhouette.InkcutPath import *
## # The simplestyle module provides functions for style parsing.
## from simplestyle import *

__version__ = '0.6'
__author__ = 'Juergen Weigert <jnweiger@gmail.com>'

N_PAGE_WIDTH = 3200
N_PAGE_HEIGHT = 800


def px2mm(px):
  '''
  Convert inkscape pixels to mm. 
  The default inkscape unit, called 'px' is 90dpi
  '''
  return px*25.4/90

# Lifted with impunity from eggbot.py
def parseLengthWithUnits( str ):

        '''
        Parse an SVG value which may or may not have units attached
        This version is greatly simplified in that it only allows: no units,
        units of px, and units of %.  Everything else, it returns None for.
        There is a more general routine to consider in scour.py if more
        generality is ever needed.
        '''

        u = 'px'
        s = str.strip()
        if s[-2:] == 'px':
                s = s[:-2]
        elif s[-1:] == '%':
                u = '%'
                s = s[:-1]

        try:
                v = float( s )
        except:
                return None, None

        return v, u


def subdivideCubicPath( sp, flat, i=1 ):

        """
        Break up a bezier curve into smaller curves, each of which
        is approximately a straight line within a given tolerance
        (the "smoothness" defined by [flat]).

        This is a modified version of cspsubdiv.cspsubdiv() rewritten
        to avoid recurrence.
        """

        while True:
                while True:
                        if i >= len( sp ):
                                return

                        p0 = sp[i - 1][1]
                        p1 = sp[i - 1][2]
                        p2 = sp[i][0]
                        p3 = sp[i][1]

                        b = ( p0, p1, p2, p3 )

                        if cspsubdiv.maxdist( b ) > flat:
                                break

                        i += 1

                one, two = beziersplitatt( b, 0.5 )
                sp[i - 1][2] = one[1]
                sp[i][0] = two[2]
                p = [one[2], one[3], two[1]]
                sp[i:1] = [p]


def distanceSquared( P1, P2 ):

        '''
        Pythagorean distance formula WITHOUT the square root.  Since
        we just want to know if the distance is less than some fixed
        fudge factor, we can just square the fudge factor once and run
        with it rather than compute square roots over and over.
        '''

        dx = P2[0] - P1[0]
        dy = P2[1] - P1[1]

        return ( dx * dx + dy * dy )


class SendtoSilhouette(inkex.Effect):
  """
  Inkscape Extension to send to a Silhouette Cameo
  """
  def __init__(self):
    # Call the base class constructor.
    inkex.Effect.__init__(self)
    self.cut = []
    self.handle = 255
    self.flatness = 0.1
    self.pathcount = 0
    self.resumeMode = False
    self.bStopped = False
    self.plotCurrentLayer = True
    self.allLayers = True
    self.step_scaling_factor = 1        # see also px2mm()
    self.ptFirst = None
    self.fPrevX = None
    self.fPrevY = None
    self.fX = None
    self.fY = None
    self.svgLastPath = 0
    self.nodeCount = 0

    self.paths = []
    self.transforms = {}
    # For handling an SVG viewbox attribute, we will need to know the
    # values of the document's <svg> width and height attributes as well
    # as establishing a transform from the viewbox to the display.
    self.docWidth = float( N_PAGE_WIDTH )
    self.docHeight = float( N_PAGE_HEIGHT )
    self.docTransform = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]

    try:
      self.tty = open("/dev/tty", 'w')
    except:
      self.tty = open("/dev/null", 'w')
    print >>self.tty, "__init__"
    
    self.OptionParser.add_option('-b', '--bbox', '--bbox-only', '--bbox_only', 
          action = 'store', dest = 'bboxonly', type = 'inkbool', default = False, 
          help='draft the objects bounding box instead of the objects')
    self.OptionParser.add_option('-m', '--media', '--media-id', '--media_id', 
          action = 'store', dest = 'media', default = '132', 
          choices=('100','101','102','106','111','112','113',
             '120','121','122','123','124','125','126','127','128','129','130',
             '131','132','133','134','135','136','137','138','300'), 
          help="113 = pen, 132 = printer paper, 300 = custom")
    self.OptionParser.add_option('-M', '--multipass', 
          action = 'store', dest = 'multipass', type = 'int', default = '1', 
           help="[1..8], cut/draw each path object multiple times.")
    self.OptionParser.add_option('-p', '--pressure', 
          action = 'store', dest = 'pressure', type = 'int', default = 10, 
          help="[1..33], or 0 for media default")
    self.OptionParser.add_option('-s', '--speed', 
          action = 'store', dest = 'speed', type = 'int', default = 10, 
          help="[1..10], or 0 for media default")
    self.OptionParser.add_option( "-S", "--smoothness", action="store", type="float",
          dest="smoothness", default=.2, help="Smoothness of curves" )
    self.OptionParser.add_option('-t', '--tool', action = 'store',
          choices=('cut', 'pen'), dest = 'tool', default = None, help="Optimize for pen or knive")
    self.OptionParser.add_option('-w', '--wait', '--wait-done', '--wait_done', 
          action = 'store', dest = 'wait_done', type = 'inkbool', default = False, 
          help='After sending wait til device reports ready')
    self.OptionParser.add_option('-x', '--x-off', '--x_off', action = 'store',
          type = 'float', dest = 'x_off', default = 0.0, help="X-Offset [mm]")
    self.OptionParser.add_option('-y', '--y-off', '--y_off', action = 'store',
          type = 'float', dest = 'y_off', default = 0.0, help="Y-Offset [mm]")

  def penUp(self):
    # print >>self.tty, "\r penUp dummy";

  def penDown(self):
    # print >>self.tty, "\r penDown (%g,%g)" % (self.fPrevX,self.fPrevY);
    self.paths.append([(self.fPrevX,self.fPrevY)])

  def plotLineAndTime( self ):
    '''
    Send commands out the com port as a line segment (dx, dy) and a time (ms) the segment
    should take to implement
    '''

    if self.bStopped:
      return
    if ( self.fPrevX is None ):
      return
    # assuming that penDown() was called before.
    self.paths[-1].append((self.fPrevX,self.fPrevY))

    # print >>self.tty, "\r plotLineAndTime((%g,%g)-(%g,%g)) " % (self.fPrevX,self.fPrevY, self.fX, self.fY);


  ## lifted from eggbot.py, gratefully bowing to the author
  def plotPath( self, path, matTransform ):
                '''
                Plot the path while applying the transformation defined
                by the matrix [matTransform].
                '''
                # turn this path into a cubicsuperpath (list of beziers)...

                d = path.get( 'd' )

                if len( simplepath.parsePath( d ) ) == 0:
                        return

                p = cubicsuperpath.parsePath( d )

                # ...and apply the transformation to each point
                applyTransformToPath( matTransform, p )

                # p is now a list of lists of cubic beziers [control pt1, control pt2, endpoint]
                # where the start-point is the last point in the previous segment.
                for sp in p:

                        subdivideCubicPath( sp, self.options.smoothness )
                        nIndex = 0

                        for csp in sp:

                                if self.bStopped:
                                        return

                                if self.plotCurrentLayer:
                                        if nIndex == 0:
                                                self.penUp()
                                                self.virtualPenIsUp = True
                                        elif nIndex == 1:
                                                self.penDown()
                                                self.virtualPenIsUp = False

                                nIndex += 1

                                self.fX = float( csp[1][0] ) / self.step_scaling_factor
                                self.fY = float( csp[1][1] ) / self.step_scaling_factor

                                # store home
                                if self.ptFirst is None:
                                        self.ptFirst = ( self.fX, self.fY )

                                if self.plotCurrentLayer:
                                        self.plotLineAndTime()
                                        self.fPrevX = self.fX
                                        self.fPrevY = self.fY


  def recursivelyTraverseSvg( self, aNodeList,
                        matCurrent=[[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
                        parent_visibility='visible' ):
                """
                Recursively traverse the svg file to plot out all of the
                paths.  The function keeps track of the composite transformation
                that should be applied to each path.

                This function handles path, group, line, rect, polyline, polygon,
                circle, ellipse and use (clone) elements.  Notable elements not
                handled include text.  Unhandled elements should be converted to
                paths in Inkscape.
                """
                for node in aNodeList:
                        # Ignore invisible nodes
                        v = node.get( 'visibility', parent_visibility )
                        if v == 'inherit':
                                v = parent_visibility
                        if v == 'hidden' or v == 'collapse':
                                pass

                        # first apply the current matrix transform to this node's tranform
                        matNew = composeTransform( matCurrent, parseTransform( node.get( "transform" ) ) )

                        if node.tag == inkex.addNS( 'g', 'svg' ) or node.tag == 'g':

                                self.penUp()
                                if ( node.get( inkex.addNS( 'groupmode', 'inkscape' ) ) == 'layer' ):
                                        if not self.allLayers:
                                                #inkex.errormsg('Plotting layer named: ' + node.get(inkex.addNS('label', 'inkscape')))
                                                self.DoWePlotLayer( node.get( inkex.addNS( 'label', 'inkscape' ) ) )
                                self.recursivelyTraverseSvg( node, matNew, parent_visibility=v )

                        elif node.tag == inkex.addNS( 'use', 'svg' ) or node.tag == 'use':

                                # A <use> element refers to another SVG element via an xlink:href="#blah"
                                # attribute.  We will handle the element by doing an XPath search through
                                # the document, looking for the element with the matching id="blah"
                                # attribute.  We then recursively process that element after applying
                                # any necessary (x,y) translation.
                                #
                                # Notes:
                                #  1. We ignore the height and width attributes as they do not apply to
                                #     path-like elements, and
                                #  2. Even if the use element has visibility="hidden", SVG still calls
                                #     for processing the referenced element.  The referenced element is
                                #     hidden only if its visibility is "inherit" or "hidden".

                                refid = node.get( inkex.addNS( 'href', 'xlink' ) )
                                if refid:
                                        # [1:] to ignore leading '#' in reference
                                        path = '//*[@id="%s"]' % refid[1:]
                                        refnode = node.xpath( path )
                                        if refnode:
                                                x = float( node.get( 'x', '0' ) )
                                                y = float( node.get( 'y', '0' ) )
                                                # Note: the transform has already been applied
                                                if ( x != 0 ) or (y != 0 ):
                                                        matNew2 = composeTransform( matNew, parseTransform( 'translate(%f,%f)' % (x,y) ) )
                                                else:
                                                        matNew2 = matNew
                                                v = node.get( 'visibility', v )
                                                self.recursivelyTraverseSvg( refnode, matNew2, parent_visibility=v )
                                        else:
                                                pass
                                else:
                                        pass

                        elif node.tag == inkex.addNS( 'path', 'svg' ):

                                self.pathcount += 1

                                # if we're in resume mode AND self.pathcount < self.svgLastPath,
                                #    then skip over this path.
                                # if we're in resume mode and self.pathcount = self.svgLastPath,
                                #    then start here, and set
                                # self.nodeCount equal to self.svgLastPathNC
                                if self.resumeMode and ( self.pathcount == self.svgLastPath ):
                                        self.nodeCount = self.svgLastPathNC
                                if self.resumeMode and ( self.pathcount < self.svgLastPath ):
                                        pass
                                else:
                                        self.plotPath( node, matNew )
                                        if ( not self.bStopped ):       #an "index" for resuming plots quickly-- record last complete path
                                                self.svgLastPath += 1
                                                self.svgLastPathNC = self.nodeCount

                        elif node.tag == inkex.addNS( 'rect', 'svg' ) or node.tag == 'rect':

                                # Manually transform
                                #
                                #    <rect x="X" y="Y" width="W" height="H"/>
                                #
                                # into
                                #
                                #    <path d="MX,Y lW,0 l0,H l-W,0 z"/>
                                #
                                # I.e., explicitly draw three sides of the rectangle and the
                                # fourth side implicitly

                                self.pathcount += 1
                                # if we're in resume mode AND self.pathcount < self.svgLastPath,
                                #    then skip over this path.
                                # if we're in resume mode and self.pathcount = self.svgLastPath,
                                #    then start here, and set
                                # self.nodeCount equal to self.svgLastPathNC
                                if self.resumeMode and ( self.pathcount == self.svgLastPath ):
                                        self.nodeCount = self.svgLastPathNC
                                if self.resumeMode and ( self.pathcount < self.svgLastPath ):
                                        pass
                                else:
                                        # Create a path with the outline of the rectangle
                                        newpath = inkex.etree.Element( inkex.addNS( 'path', 'svg' ) )
                                        x = float( node.get( 'x' ) )
                                        y = float( node.get( 'y' ) )
                                        w = float( node.get( 'width' ) )
                                        h = float( node.get( 'height' ) )
                                        s = node.get( 'style' )
                                        if s:
                                                newpath.set( 'style', s )
                                        t = node.get( 'transform' )
                                        if t:
                                                newpath.set( 'transform', t )
                                        a = []
                                        a.append( ['M ', [x, y]] )
                                        a.append( [' l ', [w, 0]] )
                                        a.append( [' l ', [0, h]] )
                                        a.append( [' l ', [-w, 0]] )
                                        a.append( [' Z', []] )
                                        newpath.set( 'd', simplepath.formatPath( a ) )
                                        self.plotPath( newpath, matNew )

                        elif node.tag == inkex.addNS( 'line', 'svg' ) or node.tag == 'line':

                                # Convert
                                #
                                #   <line x1="X1" y1="Y1" x2="X2" y2="Y2/>
                                #
                                # to
                                #
                                #   <path d="MX1,Y1 LX2,Y2"/>

                                self.pathcount += 1
                                # if we're in resume mode AND self.pathcount < self.svgLastPath,
                                #    then skip over this path.
                                # if we're in resume mode and self.pathcount = self.svgLastPath,
                                #    then start here, and set
                                # self.nodeCount equal to self.svgLastPathNC

                                if self.resumeMode and ( self.pathcount == self.svgLastPath ):
                                        self.nodeCount = self.svgLastPathNC
                                if self.resumeMode and ( self.pathcount < self.svgLastPath ):
                                        pass
                                else:
                                        # Create a path to contain the line
                                        newpath = inkex.etree.Element( inkex.addNS( 'path', 'svg' ) )
                                        x1 = float( node.get( 'x1' ) )
                                        y1 = float( node.get( 'y1' ) )
                                        x2 = float( node.get( 'x2' ) )
                                        y2 = float( node.get( 'y2' ) )
                                        s = node.get( 'style' )
                                        if s:
                                                newpath.set( 'style', s )
                                        t = node.get( 'transform' )
                                        if t:
                                                newpath.set( 'transform', t )
                                        a = []
                                        a.append( ['M ', [x1, y1]] )
                                        a.append( [' L ', [x2, y2]] )
                                        newpath.set( 'd', simplepath.formatPath( a ) )
                                        self.plotPath( newpath, matNew )
                                        if ( not self.bStopped ):       #an "index" for resuming plots quickly-- record last complete path
                                                self.svgLastPath += 1
                                                self.svgLastPathNC = self.nodeCount

                        elif node.tag == inkex.addNS( 'polyline', 'svg' ) or node.tag == 'polyline':

                                # Convert
                                #
                                #  <polyline points="x1,y1 x2,y2 x3,y3 [...]"/>
                                #
                                # to
                                #
                                #   <path d="Mx1,y1 Lx2,y2 Lx3,y3 [...]"/>
                                #
                                # Note: we ignore polylines with no points

                                pl = node.get( 'points', '' ).strip()
                                if pl == '':
                                        pass

                                self.pathcount += 1
                                #if we're in resume mode AND self.pathcount < self.svgLastPath, then skip over this path.
                                #if we're in resume mode and self.pathcount = self.svgLastPath, then start here, and set
                                # self.nodeCount equal to self.svgLastPathNC

                                if self.resumeMode and ( self.pathcount == self.svgLastPath ):
                                        self.nodeCount = self.svgLastPathNC

                                if self.resumeMode and ( self.pathcount < self.svgLastPath ):
                                        pass

                                else:
                                        pa = pl.split()
                                        if not len( pa ):
                                                pass
                                        # Issue 29: pre 2.5.? versions of Python do not have
                                        #    "statement-1 if expression-1 else statement-2"
                                        # which came out of PEP 308, Conditional Expressions
                                        #d = "".join( ["M " + pa[i] if i == 0 else " L " + pa[i] for i in range( 0, len( pa ) )] )
                                        d = "M " + pa[0]
                                        for i in range( 1, len( pa ) ):
                                                d += " L " + pa[i]
                                        newpath = inkex.etree.Element( inkex.addNS( 'path', 'svg' ) )
                                        newpath.set( 'd', d );
                                        s = node.get( 'style' )
                                        if s:
                                                newpath.set( 'style', s )
                                        t = node.get( 'transform' )
                                        if t:
                                                newpath.set( 'transform', t )
                                        self.plotPath( newpath, matNew )
                                        if ( not self.bStopped ):       #an "index" for resuming plots quickly-- record last complete path
                                                self.svgLastPath += 1
                                                self.svgLastPathNC = self.nodeCount

                        elif node.tag == inkex.addNS( 'polygon', 'svg' ) or node.tag == 'polygon':

                                # Convert
                                #
                                #  <polygon points="x1,y1 x2,y2 x3,y3 [...]"/>
                                #
                                # to
                                #
                                #   <path d="Mx1,y1 Lx2,y2 Lx3,y3 [...] Z"/>
                                #
                                # Note: we ignore polygons with no points

                                pl = node.get( 'points', '' ).strip()
                                if pl == '':
                                        pass

                                self.pathcount += 1
                                #if we're in resume mode AND self.pathcount < self.svgLastPath, then skip over this path.
                                #if we're in resume mode and self.pathcount = self.svgLastPath, then start here, and set
                                # self.nodeCount equal to self.svgLastPathNC

                                if self.resumeMode and ( self.pathcount == self.svgLastPath ):
                                        self.nodeCount = self.svgLastPathNC

                                if self.resumeMode and ( self.pathcount < self.svgLastPath ):
                                        pass

                                else:
                                        pa = pl.split()
                                        if not len( pa ):
                                                pass
                                        # Issue 29: pre 2.5.? versions of Python do not have
                                        #    "statement-1 if expression-1 else statement-2"
                                        # which came out of PEP 308, Conditional Expressions
                                        #d = "".join( ["M " + pa[i] if i == 0 else " L " + pa[i] for i in range( 0, len( pa ) )] )
                                        d = "M " + pa[0]
                                        for i in range( 1, len( pa ) ):
                                                d += " L " + pa[i]
                                        d += " Z"
                                        newpath = inkex.etree.Element( inkex.addNS( 'path', 'svg' ) )
                                        newpath.set( 'd', d );
                                        s = node.get( 'style' )
                                        if s:
                                                newpath.set( 'style', s )
                                        t = node.get( 'transform' )
                                        if t:
                                                newpath.set( 'transform', t )
                                        self.plotPath( newpath, matNew )
                                        if ( not self.bStopped ):       #an "index" for resuming plots quickly-- record last complete path
                                                self.svgLastPath += 1
                                                self.svgLastPathNC = self.nodeCount

                        elif node.tag == inkex.addNS( 'ellipse', 'svg' ) or \
                                node.tag == 'ellipse' or \
                                node.tag == inkex.addNS( 'circle', 'svg' ) or \
                                node.tag == 'circle':

                                        # Convert circles and ellipses to a path with two 180 degree arcs.
                                        # In general (an ellipse), we convert
                                        #
                                        #   <ellipse rx="RX" ry="RY" cx="X" cy="Y"/>
                                        #
                                        # to
                                        #
                                        #   <path d="MX1,CY A RX,RY 0 1 0 X2,CY A RX,RY 0 1 0 X1,CY"/>
                                        #
                                        # where
                                        #
                                        #   X1 = CX - RX
                                        #   X2 = CX + RX
                                        #
                                        # Note: ellipses or circles with a radius attribute of value 0 are ignored

                                        if node.tag == inkex.addNS( 'ellipse', 'svg' ) or node.tag == 'ellipse':
                                                rx = float( node.get( 'rx', '0' ) )
                                                ry = float( node.get( 'ry', '0' ) )
                                        else:
                                                rx = float( node.get( 'r', '0' ) )
                                                ry = rx
                                        if rx == 0 or ry == 0:
                                                pass

                                        self.pathcount += 1
                                        #if we're in resume mode AND self.pathcount < self.svgLastPath, then skip over this path.
                                        #if we're in resume mode and self.pathcount = self.svgLastPath, then start here, and set
                                        # self.nodeCount equal to self.svgLastPathNC

                                        if self.resumeMode and ( self.pathcount == self.svgLastPath ):
                                                self.nodeCount = self.svgLastPathNC

                                        if self.resumeMode and ( self.pathcount < self.svgLastPath ):
                                                pass

                                        else:
                                                cx = float( node.get( 'cx', '0' ) )
                                                cy = float( node.get( 'cy', '0' ) )
                                                x1 = cx - rx
                                                x2 = cx + rx
                                                d = 'M %f,%f ' % ( x1, cy ) + \
                                                        'A %f,%f ' % ( rx, ry ) + \
                                                        '0 1 0 %f,%f ' % ( x2, cy ) + \
                                                        'A %f,%f ' % ( rx, ry ) + \
                                                        '0 1 0 %f,%f' % ( x1, cy )
                                                newpath = inkex.etree.Element( inkex.addNS( 'path', 'svg' ) )
                                                newpath.set( 'd', d );
                                                s = node.get( 'style' )
                                                if s:
                                                        newpath.set( 'style', s )
                                                t = node.get( 'transform' )
                                                if t:
                                                        newpath.set( 'transform', t )
                                                self.plotPath( newpath, matNew )
                                                if ( not self.bStopped ):       #an "index" for resuming plots quickly-- record last complete path
                                                        self.svgLastPath += 1
                                                        self.svgLastPathNC = self.nodeCount
                        elif node.tag == inkex.addNS( 'metadata', 'svg' ) or node.tag == 'metadata':
                                pass
                        elif node.tag == inkex.addNS( 'defs', 'svg' ) or node.tag == 'defs':
                                pass
                        elif node.tag == inkex.addNS( 'namedview', 'sodipodi' ) or node.tag == 'namedview':
                                pass
                        elif node.tag == inkex.addNS( 'eggbot', 'svg' ) or node.tag == 'eggbot':
                                pass
                        elif node.tag == inkex.addNS( 'title', 'svg' ) or node.tag == 'title':
                                pass
                        elif node.tag == inkex.addNS( 'desc', 'svg' ) or node.tag == 'desc':
                                pass
                        elif node.tag == inkex.addNS( 'text', 'svg' ) or node.tag == 'text':
                                if not self.warnings.has_key( 'text' ):
                                        inkex.errormsg( gettext.gettext( 'Warning: unable to draw text; ' +
                                                'please convert it to a path first.  Consider using the ' +
                                                'Hershey Text extension which is located under the '+
                                                '"Render" category of extensions.' ) )
                                        self.warnings['text'] = 1
                                pass
                        elif node.tag == inkex.addNS( 'image', 'svg' ) or node.tag == 'image':
                                if not self.warnings.has_key( 'image' ):
                                        inkex.errormsg( gettext.gettext( 'Warning: unable to draw bitmap images; ' +
                                                'please convert them to line art first.  Consider using the "Trace bitmap..." ' +
                                                'tool of the "Path" menu.  Mac users please note that some X11 settings may ' +
                                                'cause cut-and-paste operations to paste in bitmap copies.' ) )
                                        self.warnings['image'] = 1
                                pass
                        elif node.tag == inkex.addNS( 'pattern', 'svg' ) or node.tag == 'pattern':
                                pass
                        elif node.tag == inkex.addNS( 'radialGradient', 'svg' ) or node.tag == 'radialGradient':
                                # Similar to pattern
                                pass
                        elif node.tag == inkex.addNS( 'linearGradient', 'svg' ) or node.tag == 'linearGradient':
                                # Similar in pattern
                                pass
                        elif node.tag == inkex.addNS( 'style', 'svg' ) or node.tag == 'style':
                                # This is a reference to an external style sheet and not the value
                                # of a style attribute to be inherited by child elements
                                pass
                        elif node.tag == inkex.addNS( 'cursor', 'svg' ) or node.tag == 'cursor':
                                pass
                        elif node.tag == inkex.addNS( 'color-profile', 'svg' ) or node.tag == 'color-profile':
                                # Gamma curves, color temp, etc. are not relevant to single color output
                                pass
                        elif not isinstance( node.tag, basestring ):
                                # This is likely an XML processing instruction such as an XML
                                # comment.  lxml uses a function reference for such node tags
                                # and as such the node tag is likely not a printable string.
                                # Further, converting it to a printable string likely won't
                                # be very useful.
                                pass
                        else:
                                if not self.warnings.has_key( str( node.tag ) ):
                                        t = str( node.tag ).split( '}' )
                                        inkex.errormsg( gettext.gettext( 'Warning: unable to draw <' + str( t[-1] ) +
                                                '> object, please convert it to a path first.' ) )
                                        self.warnings[str( node.tag )] = 1
                                pass


  def getLength( self, name, default ):

                '''
                Get the <svg> attribute with name "name" and default value "default"
                Parse the attribute into a value and associated units.  Then, accept
                no units (''), units of pixels ('px'), and units of percentage ('%').
                '''

                str = self.document.getroot().get( name )
                if str:
                        v, u = parseLengthWithUnits( str )
                        if not v:
                                # Couldn't parse the value
                                return None
                        elif ( u == '' ) or ( u == 'px' ):
                                return v
                        elif u == '%':
                                return float( default ) * v / 100.0
                        else:
                                # Unsupported units
                                return None
                else:
                        # No width specified; assume the default value
                        return float( default )


  def getDocProps( self ):

                '''
                Get the document's height and width attributes from the <svg> tag.
                Use a default value in case the property is not present or is
                expressed in units of percentages.
                '''

                self.docHeight = self.getLength( 'height', N_PAGE_HEIGHT )
                self.docWidth = self.getLength( 'width', N_PAGE_WIDTH )
                if ( self.docHeight == None ) or ( self.docWidth == None ):
                        return False
                else:
                        return True


  def handleViewBox( self ):

                '''
                Set up the document-wide transform in the event that the document has an SVG viewbox
                '''

                if self.getDocProps():
                        viewbox = self.document.getroot().get( 'viewBox' )
                        if viewbox:
                                vinfo = viewbox.strip().replace( ',', ' ' ).split( ' ' )
                                if ( vinfo[2] != 0 ) and ( vinfo[3] != 0 ):
                                        sx = self.docWidth / float( vinfo[2] )
                                        sy = self.docHeight / float( vinfo[3] )
                                        self.docTransform = parseTransform( 'scale(%f,%f)' % (sx, sy) )


  def effect(self):
    try:
      dev = SilhouetteCameo(log=self.tty, dummy=False)
    except Exception as e:
      print >>self.tty, e
      print >>sys.stderr, e
      return
    state = dev.status()    # hint at loading paper, if not ready.
    print >>self.tty, "status=%s" % (state)
    print >>self.tty, "device version: '%s'" % dev.get_version()

    # Viewbox handling
    self.handleViewBox()
    # Build a list of the vertices for the document's graphical elements
    if self.options.ids:
      # Traverse the selected objects
      for id in self.options.ids:
        self.recursivelyTraverseSvg( [self.selected[id]], self.docTransform )
    else:
      # Traverse the entire document
      self.recursivelyTraverseSvg( self.document.getroot(), self.docTransform )
    ## # -------------------------
    ## nodes = self.selected.keys()
    ## # If no nodes are selected, then cut the whole document. 
    ## # if len(nodes) == 0: 
    ## #   nodes = self.doc_ids.keys()[0]    # only the first. All other objects are children anyway.

    ## def getSelectedById(IDlist): # returns lxml elements that have an id in IDlist in the svg
    ##   ele=[]
    ##   svg = self.document.getroot()
    ##   for e in svg.iterfind('.//*[@id]'):
    ##     if IDlist is None or e.get('id') in IDlist:
    ##       ele.append(e)
    ##   return ele

    ## lxml_nodes = []
    ## if len(nodes):
    ##   selected = getSelectedById(nodes)
    ## else:
    ##   selected = self.document.getroot()
    ## for node in selected:
    ##   tag = node.tag[node.tag.rfind("}")+1:]
    ##   if tag in ('grid','namedview','defs','metadata'): continue
    ##   lxml_nodes.append(node)
    ## print >>self.tty, "Nodecount: %d\n" % len(lxml_nodes)

    ## # import xml.etree.ElementTree as ET
    ## # ET.tostring(lxml_nodes[0])

    ## ## This is from better_dxf_output.py: quite lousy implementation.
    ## ## it silently ignores transformation on path objects and cannot really handle rects.
    ## self.plot = Plot({
    ##   'scale':25.4/units['in'], 'margin':0, 'startPosition':(0,0), 
    ##   'smoothness':0.2*units['mm']})
    ## self.plot.loadGraphic(lxml_nodes)
    ## cut = self.plot.toCutList(self.options.multipass)
    ## # print >>self.tty, self.plot.graphic, cut
    ## cut = dev.flip_cut(cut)

    ## Do not use the code above: recursivelyTraverseSvg() from egbot.py
    ## is much more mature.

    cut = []
    for px_path in self.paths:
      mm_path = [] 
      for pt in px_path:
        mm_path.append((px2mm(pt[0]), px2mm(pt[1])))
      for i in range(0,self.options.multipass): 
        cut.append(mm_path)

    if self.options.pressure == 0:     self.options.pressure = None
    if self.options.speed == 0:        self.options.speed = None
    pen=None
    if self.options.tool == 'pen': pen=True
    if self.options.tool == 'cut': pen=False
    if self.options.bboxonly == False: self.options.bboxonly=None
    dev.setup(media=self.options.media, pen=pen, 
      pressure=self.options.pressure, speed=self.options.speed)
    bbox = dev.page(cut=cut, 
      mediawidth=px2mm(self.docWidth), 
      mediaheight=px2mm(self.docHeight), 
      offset=(self.options.x_off,self.options.y_off),
      bboxonly=self.options.bboxonly)
    if len(bbox['bbox'].keys()) == 0:
      print >>self.tty, "empty page?"
      print >>sys.stderr, "empty page?"
    else:
      print >>self.tty, " 100%%, bbox: (%.1f,%.1f)-(%.1f,%.1f)mm, %d points" % (
        bbox['bbox']['llx']*bbox['unit'],
        bbox['bbox']['ury']*bbox['unit'],
        bbox['bbox']['urx']*bbox['unit'],
        bbox['bbox']['lly']*bbox['unit'],
        bbox['total'])
      state = dev.status()
      while self.options.wait_done and state == 'moving':
        self.tty.write('.')
        self.tty.flush()
        state = dev.status()
        time.sleep(1)
    print >>self.tty, "\nstatus=%s" % (state)

    # pump the output to the device
    success = True
    if not success:
      logging.error('Failed to put output to device')
    output = ""
    return output

e = SendtoSilhouette()
start = time.time()
e.affect()
ss = int(time.time()-start+.5)
mm = int(ss/60)
ss -= mm*60
print >>e.tty, " done. %d min %d sec" % (mm,ss)