

CREATE OR REPLACE PROCEDURE sp_refresh_mart_daily_summary()
LANGUAGE plpgsql AS $$
DECLARE
    v_row_count INT;
BEGIN
    TRUNCATE TABLE mart_daily_summary;

    INSERT INTO mart_daily_summary
        (summary_date, source_name, total_articles, scored_articles, avg_sentiment, avg_push_count)
    SELECT
        f.fact_date              AS summary_date,
        f.source_name,
        SUM(f.article_count)                                                                  AS total_articles,
        SUM(f.scored_articles)                                                                AS scored_articles,
        SUM(f.avg_sentiment  * f.scored_articles) / NULLIF(SUM(f.scored_articles), 0)         AS avg_sentiment,
        SUM(f.avg_push_count * f.article_count)   / NULLIF(SUM(f.article_count), 0)           AS avg_push_count
    FROM fact_sentiment f
    GROUP BY f.fact_date, f.source_name;

    GET DIAGNOSTICS v_row_count = ROW_COUNT;
    RAISE NOTICE 'mart_daily_summary refreshed: % rows', v_row_count;
END;
$$;

CREATE OR REPLACE PROCEDURE sp_refresh_mart_market_summary()
LANGUAGE plpgsql AS $$
DECLARE
    v_row_count INT;
BEGIN
    TRUNCATE TABLE mart_market_summary;

    INSERT INTO mart_market_summary
        (fact_date, market_code, source_count, total_articles, scored_articles,
         avg_sentiment, avg_push_count)
    SELECT
        fs.fact_date,
        dm.market_code,
        COUNT(DISTINCT ds.source_id)                                                            AS source_count,
        SUM(fs.article_count)                                                                   AS total_articles,
        SUM(fs.scored_articles)                                                                 AS scored_articles,
        SUM(fs.avg_sentiment  * fs.scored_articles) / NULLIF(SUM(fs.scored_articles), 0)        AS avg_sentiment,
        SUM(fs.avg_push_count * fs.article_count)   / NULLIF(SUM(fs.article_count), 0)          AS avg_push_count
    FROM fact_sentiment fs
    JOIN dim_source ds ON ds.source_id = fs.source_id
    JOIN dim_market dm ON dm.market_id = ds.market_id
    GROUP BY fs.fact_date, dm.market_code;

    GET DIAGNOSTICS v_row_count = ROW_COUNT;
    RAISE NOTICE 'mart_market_summary refreshed: % rows', v_row_count;
END;
$$;

CREATE OR REPLACE PROCEDURE sp_populate_fact_sentiment()
LANGUAGE plpgsql AS $$
DECLARE
    v_row_count INT;
BEGIN
    INSERT INTO fact_sentiment
        (fact_date, source_id, stock_symbol, source_name,
         article_count, scored_articles, avg_sentiment, avg_push_count)
    SELECT
        a.published_at::DATE                                  AS fact_date,
        a.source_id,
        ds.tracked_stock                                      AS stock_symbol,
        s.source_name,
        COUNT(a.article_id)                                   AS article_count,
        COUNT(*) FILTER (WHERE ss.score IS NOT NULL)::INTEGER AS scored_articles,
        AVG(ss.score)                                         AS avg_sentiment,
        AVG(a.push_count)                                     AS avg_push_count
    FROM articles a
    JOIN sources s                    ON s.source_id  = a.source_id
    LEFT JOIN dim_source ds           ON ds.source_id = a.source_id
    LEFT JOIN sentiment_scores ss     ON ss.article_id = a.article_id
    GROUP BY
        a.published_at::DATE,
        a.source_id,
        ds.tracked_stock,
        s.source_name
    ON CONFLICT (fact_date, source_id) DO UPDATE
        SET article_count   = EXCLUDED.article_count,
            scored_articles = EXCLUDED.scored_articles,
            avg_sentiment   = EXCLUDED.avg_sentiment,
            avg_push_count  = EXCLUDED.avg_push_count,
            stock_symbol    = EXCLUDED.stock_symbol;

    GET DIAGNOSTICS v_row_count = ROW_COUNT;
    RAISE NOTICE 'fact_sentiment upserted: % rows', v_row_count;
END;
$$;

DROP FUNCTION IF EXISTS fn_get_daily_sentiment(DATE, INT);

CREATE OR REPLACE FUNCTION fn_get_daily_sentiment(
    target_date DATE DEFAULT CURRENT_DATE,
    days        INT  DEFAULT 30
)
RETURNS TABLE (
    summary_date    DATE,
    source_name     VARCHAR,
    total_articles  BIGINT,
    scored_articles BIGINT,
    avg_sentiment   NUMERIC
)
LANGUAGE sql STABLE AS $$
    SELECT
        m.summary_date,
        m.source_name,
        SUM(m.total_articles)::BIGINT                          AS total_articles,
        SUM(m.scored_articles)::BIGINT                         AS scored_articles,
        SUM(m.avg_sentiment * m.scored_articles)
            / NULLIF(SUM(m.scored_articles), 0)                AS avg_sentiment
    FROM mart_daily_summary m
    WHERE m.summary_date <= target_date
      AND m.summary_date >  target_date - (days * INTERVAL '1 day')
      AND m.avg_sentiment IS NOT NULL
    GROUP BY m.summary_date, m.source_name
    ORDER BY m.summary_date DESC, m.source_name;
$$;

DO $$
BEGIN
    RAISE NOTICE '[init_marts] Objects created:';
    RAISE NOTICE '  - sp_refresh_mart_daily_summary  (PROCEDURE)';
    RAISE NOTICE '  - sp_refresh_mart_market_summary (PROCEDURE)';
    RAISE NOTICE '  - sp_populate_fact_sentiment     (PROCEDURE)';
    RAISE NOTICE '  - fn_get_daily_sentiment         (FUNCTION, STABLE)';
    RAISE NOTICE '[init_marts] Use CALL / SELECT accordingly.';
END $$;
