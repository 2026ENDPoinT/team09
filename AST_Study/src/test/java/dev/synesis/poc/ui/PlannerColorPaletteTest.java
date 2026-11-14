package dev.synesis.poc.ui;

import dev.synesis.poc.planner.*;
import dev.synesis.poc.planner.PlannerModel.Event;
import java.awt.*;
import java.awt.event.*;
import java.awt.image.BufferedImage;
import java.nio.file.Files;
import java.time.*;
import java.util.List;
import java.util.concurrent.atomic.AtomicReference;
import javax.swing.*;
import static dev.synesis.poc.planner.PlannerModel.*;

/** All palette colors stay readable, persist intact, and remain reachable in a horizontal row. */
public final class PlannerColorPaletteTest {
    public static void main(String[] args)throws Exception {
        PlannerStore store=new PlannerStore(Files.createTempDirectory("planner-colors-").resolve("planner.json"));
        if(EventColor.values().length!=12)throw new AssertionError("expected twelve colors");
        LocalDateTime start=LocalDateTime.of(2026,10,22,10,0);
        for(EventColor color:EventColor.values())store.saveEvent(new Event("color-"+color.name(),"현예이 시험","",start,start.plusHours(2),false,color,List.of(),false,Repeat.NONE,-1));
        State state=store.load();
        for(EventColor value:EventColor.values()) {
            if(state.events().stream().noneMatch(e->e.color()==value))throw new AssertionError("saved color lost: "+value);
            Color color=new Color(value.rgb),fill=PlannerEventCard.background(color),stripe=PlannerEventCard.accent(color),fg=PlannerEventCard.foreground(fill),time=PlannerEventCard.secondaryForeground(fill),chip=PlannerEventCard.chipFill(fill);
            float[] baseHsv=Color.RGBtoHSB(color.getRed(),color.getGreen(),color.getBlue(),null),fillHsv=Color.RGBtoHSB(fill.getRed(),fill.getGreen(),fill.getBlue(),null),stripeHsv=Color.RGBtoHSB(stripe.getRed(),stripe.getGreen(),stripe.getBlue(),null);
            if(PlannerEventCard.luminance(fill)<.8 || fillHsv[1]>.12 || stripeHsv[1]<fillHsv[1]+.1 || Math.abs(baseHsv[0]-stripeHsv[0])>.02)
                throw new AssertionError("pastel fill / same-family saturated stripe relationship lost: "+value);
            if(contrast(fill,fg)<4.5 || contrast(fill,time)<4.5 || contrast(chip,PlannerEventCard.foreground(chip))<4.5)
                throw new AssertionError("insufficient title/time/tag contrast: "+value);
            BufferedImage image=new BufferedImage(248,132,BufferedImage.TYPE_INT_RGB);
            Graphics2D g=image.createGraphics();PlannerEventCard.paint(g,0,0,248,132,"현예이 시험","10:00–22:00",color,List.of("중간고사"));g.dispose();
            if(image.getRGB(230,110)!=fill.getRGB())throw new AssertionError("card fill not pastel: "+value);
            if(image.getRGB(2,30)!=stripe.getRGB())throw new AssertionError("stripe not saturated accent: "+value);
            if(!hasPixel(image,new Rectangle(16,12,180,22),fg)||!hasPixel(image,new Rectangle(16,40,180,20),time)
                ||!hasPixel(image,new Rectangle(26,72,70,20),PlannerEventCard.foreground(chip)))
                throw new AssertionError("title/time/tag not painted with readable ink: "+value);
        }
        SwingUtilities.invokeAndWait(()->{
            PlannerDesign planner=new PlannerDesign(store,Clock.fixed(Instant.parse("2026-10-22T02:00:00Z"),ZoneId.of("Asia/Seoul")));
            planner.setMonthly(true);
            for(Event event:state.events()) {
                JButton actual=planner.eventButton(new Occurrence(event,event.start(),event.end()),true);
                BufferedImage image=new BufferedImage(180,52,BufferedImage.TYPE_INT_RGB);actual.setSize(180,52);
                Graphics2D g=image.createGraphics();actual.printAll(g);g.dispose();
                Color color=new Color(event.color().rgb);
                if(image.getRGB(160,40)!=PlannerEventCard.background(color).getRGB() || image.getRGB(2,25)!=PlannerEventCard.accent(color).getRGB())
                    throw new AssertionError("monthly event has inconsistent color: "+event.color());
            }
            AtomicReference<EventColor> changed=new AtomicReference<>();
            PlannerColorPicker picker=new PlannerColorPicker(EventColor.PINK,changed::set);
            picker.setSize(336,40);layout(picker);
            if(!picker.getHorizontalScrollBar().isVisible()||picker.getVerticalScrollBar().isVisible())throw new AssertionError("palette must scroll only horizontally");
            if(picker.getViewport().getViewPosition().x<=0)throw new AssertionError("existing last color is not initially visible");
            for(JButton button:picker.buttons)if(button.getHeight()<32)throw new AssertionError("palette clips a swatch");
            picker.getHorizontalScrollBar().setValue(0);
            picker.dispatchEvent(new MouseWheelEvent(picker,MouseEvent.MOUSE_WHEEL,System.currentTimeMillis(),0,20,15,0,false,MouseWheelEvent.WHEEL_UNIT_SCROLL,3,3));
            if(picker.getViewport().getViewPosition().x<=0)throw new AssertionError("ordinary wheel cannot reach later colors");
            picker.buttons.get(11).doClick();if(changed.get()!=EventColor.PINK)throw new AssertionError("last color did not reach draft callback");
            picker.setSize(220,40);layout(picker);
            if(picker.getViewport().getViewSize().width<=picker.getViewport().getExtentSize().width)throw new AssertionError("narrow palette wrapped or lost colors");
        });
        System.out.println("PlannerColorPaletteTest OK: 12 colors, storage roundtrip, contrast >=4.5, actual title/time/tag pixels, horizontal input");
        System.exit(0);
    }
    private static double contrast(Color a,Color b){double x=PlannerEventCard.luminance(a),y=PlannerEventCard.luminance(b);return (Math.max(x,y)+.05)/(Math.min(x,y)+.05);}
    private static boolean hasPixel(BufferedImage image,Rectangle area,Color color){
        for(int y=area.y;y<area.y+area.height;y++)for(int x=area.x;x<area.x+area.width;x++)if(image.getRGB(x,y)==color.getRGB())return true;
        return false;
    }
    private static void layout(Container c){c.doLayout();for(Component child:c.getComponents())if(child instanceof Container nested)layout(nested);}
}
