package dev.synesis.poc.pdf;

import java.awt.Rectangle;
import java.util.*;
import java.util.List;
import java.util.concurrent.atomic.AtomicInteger;

/** Compares the optimized candidate range with the original full scan, including gaps/edges. */
public final class PdfPageRangeTest {
    public static void main(String[] args){
        Random random=new Random(1027);List<Rectangle> pages=new ArrayList<>();int y=16;
        for(int i=0;i<10000;i++){int height=1+random.nextInt(1400);pages.add(new Rectangle(16,y,600,height));y+=height+16;}
        for(int i=0;i<600;i++){
            Rectangle region=new Rectangle(i%3==0?700:0,random.nextInt(y+200)-100,650,random.nextInt(2000));
            List<Rectangle> expected=pages.stream().filter(region::intersects).toList();AtomicInteger reads=new AtomicInteger();
            List<Rectangle> nearby=PdfPageRange.within(pages,p->{reads.incrementAndGet();return p;},region);
            List<Rectangle> actual=nearby.stream().filter(region::intersects).toList();
            check(expected.equals(actual),"candidate range changed page order/intersection");
            check(reads.get()<=30,"range lookup scans the entire document");
        }
        for(Rectangle page:pages.subList(0,5))for(int edge:new int[]{page.y-1,page.y,page.y+page.height-1,page.y+page.height}){
            Rectangle region=new Rectangle(0,edge,1000,1);
            check(pages.stream().filter(region::intersects).toList().equals(PdfPageRange.within(pages,p->p,region).stream().filter(region::intersects).toList()),"boundary differs");
        }
        check(PdfPageRange.within(List.<Rectangle>of(),p->p,new Rectangle(0,0,100,100)).isEmpty(),"empty document");
        System.out.println("PdfPageRangeTest passed: 10,000 pages, 600 viewports and exact boundaries; <=30 layout probes per lookup");
    }
    private static void check(boolean value,String message){if(!value)throw new AssertionError(message);}
}
