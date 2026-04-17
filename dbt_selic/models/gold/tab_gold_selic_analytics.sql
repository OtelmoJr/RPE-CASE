/*
    tab_gold_selic_analytics
    Visao executiva mensal da Selic — feita pra quem precisa
    precificar credito (CDC/BNPL) e acompanhar tendencia de juros.

    Agrega os dados diarios da tab_final por mes, calculando media,
    extremos, volatilidade e classificacao predominante.
*/

with diario as (
    select
        data_formatada,
        valor_diario,
        valor_anualizado,
        classificacao,
        date_trunc('month', data_formatada) as referencia_mes
    from {{ source('selic', 'tab_final') }}
    where data_formatada is not null
      and valor_anualizado is not null
),

mensal as (
    select
        cast(referencia_mes as date)                       as referencia,
        round(avg(valor_diario), 6)                        as selic_media_diaria,
        round(avg(valor_anualizado), 4)                    as selic_media_anualizada,
        round(min(valor_anualizado), 4)                    as selic_min_anualizada,
        round(max(valor_anualizado), 4)                    as selic_max_anualizada,
        round(max(valor_anualizado) - min(valor_anualizado), 4) as variacao_mensal,
        count(*)                                           as dias_uteis_mes,
        mode(classificacao)                                as classificacao_predominante,
        case
            when max(valor_anualizado) - min(valor_anualizado) > 0.5
                then 'VOLATIL'
            else 'ESTAVEL'
        end                                                as estabilidade
    from diario
    group by referencia_mes
)

select * from mensal
order by referencia
