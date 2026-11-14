package dev.synesis.poc.pdf;

import java.awt.Rectangle;
import java.util.List;
import java.util.function.Function;

/** Finds the vertical candidates in the PDF's ordered, non-overlapping page layout. */
final class PdfPageRange {
    private PdfPageRange() {}

    static <T> List<T> within(List<T> pages,Function<T,Rectangle> bounds,Rectangle region) {
        if(region.height<=0)return pages.subList(0,0);
        int low=0,high=pages.size();
        while(low<high){
            int mid=(low+high)>>>1;Rectangle page=bounds.apply(pages.get(mid));
            if((long)page.y+page.height<=region.y)low=mid+1;else high=mid;
        }
        int start=low;high=pages.size();long bottom=(long)region.y+region.height;
        while(low<high){
            int mid=(low+high)>>>1;
            if(bounds.apply(pages.get(mid)).y<bottom)low=mid+1;else high=mid;
        }
        return pages.subList(start,low);
    }
}
