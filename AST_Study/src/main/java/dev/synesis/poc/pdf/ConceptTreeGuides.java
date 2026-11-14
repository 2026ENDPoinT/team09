package dev.synesis.poc.pdf;

import java.awt.*;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import javax.swing.*;

/** Plain gutter strokes, cached during layout; painting never traverses concepts. */
final class ConceptTreeGuides {
    private record Line(int x,int top,int bottom,int end) {}
    private List<Line> lines=List.of();

    void layout(Container list) {
        List<Line> next=new ArrayList<>();
        Map<Integer,Integer> siblings=new HashMap<>();
        Map<Integer,Integer> parents=new HashMap<>();
        for(Component component:list.getComponents()) {
            if(!component.isVisible() || !(component instanceof JComponent child)
                    || !(child.getClientProperty("concept.treeDepth") instanceof Integer depth))continue;
            siblings.keySet().removeIf(level->level>depth);
            boolean card=Boolean.TRUE.equals(child.getClientProperty("concept.treeCard"));
            int halfLine=child.getFontMetrics(child.getFont()).getHeight()/2;
            int anchor=child.getY()+(card && child.getClientProperty("concept.treeAnchor") instanceof Integer offset
                ?offset:child.getInsets().top+halfLine);
            if(depth>0) {
                int x=child.getX()+depth*16-8;
                int start=siblings.getOrDefault(depth,parents.getOrDefault(depth-1,child.getY()));
                next.add(new Line(x,start,anchor,x+7));
            }
            siblings.put(depth,anchor);
            if(!card){
                parents.keySet().removeIf(level->level>=depth);
                parents.put(depth,anchor+halfLine+2);
            }
        }
        lines=List.copyOf(next);
    }

    void paint(Graphics graphics) {
        Rectangle clip=graphics.getClipBounds();
        graphics.setColor(new Color(0xCCD8E6));
        for(Line line:lines) {
            if(clip!=null && (line.bottom<clip.y || line.top>clip.y+clip.height))continue;
            graphics.drawLine(line.x,line.top,line.x,line.bottom);
            graphics.drawLine(line.x,line.bottom,line.end,line.bottom);
        }
    }
}
