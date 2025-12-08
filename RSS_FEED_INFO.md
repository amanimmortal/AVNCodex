# F95Zone RSS Feed Options & Parameters

This document outlines the parameters and specific ID codes used for customizing the F95Zone RSS feed (`latest_data.php`). This is crucial for constructing accurate search URLs and filters for the AVNCodex application.

## Base URL
`https://f95zone.to/sam/latest_alpha/latest_data.php?cmd=rss&cat=games`

## Key Parameters

- **`cmd`**: `rss` (Required for RSS format)
- **`cat`**: `games` (Restricts to the "Games" category)
- **`search`**: `[term]` (URL-encoded search term)
- **`rows`**: `[number]` (Number of items to return, e.g., `60`)
- **`prefixes[]`**: `[ID]` (Include ONLY items with this prefix/tag ID)
- **`noprefixes[]`**: `[ID]` (Exclude items with this prefix/tag ID)

## Prefix IDs (Tags)

These IDs are used for filtering by Game Status or Engine.

### Game Status
| Status      | ID  | Usage Notes |
| :---        | :-- | :--- |
| **Completed** | `18` | Games marked as finished/final. |
| **On Hold**   | `20` | Games where development is paused. |
| **Abandoned** | `22` | Games where development has officially stopped. |

> **Note:** To search for *only* "Ongoing/In Progress" games, you typically **exclude** all non-ongoing statuses:
> `noprefixes[]=18&noprefixes[]=20&noprefixes[]=22`

### Engines / Types (Verified)
| Engine/Type | ID |
| :--- | :-- |
| **RPGM** | `2` |
| **Unity** | `3` |
| **HTML** | `4` |
| **RAGS** | `5` |
| **Java** | `6` |
| **Ren'Py** | `7` |
| **VN** | `13` |
| **Others** | `14` |

*Note: Verified via browser session. Other engines (ADRIFT, Flash, QSP, Tads, Unreal, WebGL, Wolf RPG) could not be mapped due to browser limitations.*

## Sorting Options (Inferred)
Based on the page structure, the following sort parameters are used:
- **Date**: `sort=date`
- **Likes**: `sort=likes`
- **Views**: `sort=views`
- **Title**: `sort=title`
- **Rating**: `sort=rating`


### 1. Search for "Eternum" (Ongoing Only)
This search excludes Completed, On Hold, and Abandoned games, ensuring the result is an active project.
```
https://f95zone.to/sam/latest_alpha/latest_data.php?cmd=rss&cat=games&noprefixes[]=18&noprefixes[]=20&noprefixes[]=22&search=eternum&rows=60
```

### 2. Search for "Completed" Games Only
```
https://f95zone.to/sam/latest_alpha/latest_data.php?cmd=rss&cat=games&prefixes[]=18&rows=60
```

### 4. Search by Tag (e.g., "Female Protagonist")
```
https://f95zone.to/sam/latest_alpha/latest_data.php?cmd=rss&cat=games&tags=392
```

### 5. Exclude Tags (e.g., No "Horror")
```
https://f95zone.to/sam/latest_alpha/latest_data.php?cmd=rss&cat=games&notags=708
```

## Tags (Verified)
The following tags can be used with `tags=[ID]` (include) or `notags=[ID]` (exclude).

| Tag Name | ID |
| :--- | :-- |
| **2dcg** | `1507` |
| **3dcg** | `107` |
| **adventure** | `162` |
| **ahegao** | `916` |
| **ai cg** | `2265` |
| **anal sex** | `2241` |
| **animated** | `783` |
| **bdsm** | `264` |
| **bestiality** | `105` |
| **big ass** | `817` |
| **big tits** | `130` |
| **blackmail** | `339` |
| **bukkake** | `216` |
| **censored** | `2247` |
| **character creation** | `2246` |
| **cheating** | `924` |
| **combat** | `550` |
| **corruption** | `103` |
| **cosplay** | `606` |
| **creampie** | `278` |
| **dating sim** | `348` |
| **dilf** | `1407` |
| **drugs** | `2217` |
| **exhibitionism** | `384` |
| **fantasy** | `179` |
| **female domination** | `2252` |
| **female protagonist** | `392` |
| **footjob** | `553` |
| **furry** | `382` |
| **futa/trans** | `191` |
| **futa/trans protagonist** | `2255` |
| **gay** | `360` |
| **graphic violence** | `728` |
| **groping** | `535` |
| **group sex** | `498` |
| **handjob** | `259` |
| **harem** | `254` |
| **horror** | `708` |
| **humiliation** | `871` |
| **humor** | `361` |
| **incest** | `30` |
| **interracial** | `894` |
| **lactation** | `290` |
| **lesbian** | `181` |
| **male domination** | `174` |
| **male protagonist** | `173` |
| **management** | `449` |
| **masturbation** | `176` |
| **milf** | `75` |
| **mind control** | `111` |
| **mobile game** | `2229` |
| **monster** | `182` |
| **monster girl** | `394` |
| **multiple endings** | `322` |
| **multiple penetration** | `1556` |
| **multiple protagonist** | `2242` |
| **netorare** | `258` |
| **oral sex** | `237` |
| **paranormal** | `408` |
| **parody** | `505` |
| **possession** | `1476` |
| **pov** | `1766` |
| **pregnancy** | `225` |
| **prostitution** | `374` |
| **rape** | `417` |
| **real porn** | `1707` |
| **romance** | `330` |
| **rpg** | `45` |
| **sandbox** | `2257` |
| **scat** | `689` |
| **school setting** | `547` |
| **sci-fi** | `141` |
| **sex toys** | `2216` |
| **sexual harassment** | `670` |
| **simulator** | `448` |
| **sissification** | `2215` |
| **slave** | `44` |
| **sleep sex** | `1305` |
| **spanking** | `769` |
| **stripping** | `480` |
| **swinging** | `2234` |
| **teasing** | `351` |
| **tentacles** | `215` |
| **text based** | `522` |
| **titfuck** | `411` |
| **trainer** | `199` |
| **transformation** | `875` |
| **trap** | `362` |
| **turn based combat** | `452` |
| **twins** | `327` |
| **urination** | `1254` |
| **vaginal sex** | `2209` |
| **virgin** | `833` |
| **voyeurism** | `485` |

